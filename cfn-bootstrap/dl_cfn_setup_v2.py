#!/usr/bin/python

#  Copyright 2017 Amazon.com, Inc. or its affiliates. All Rights Reserved.
#
#  Licensed under the Amazon Software License (the "License").
#  You may not use this file except in compliance with the License.
#  A copy of the License is located at
#
#  http://aws.amazon.com/asl/
#
#  or in the "license" file accompanying this file. This file is distributed
#  on an "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either
#  express or implied. See the License for the specific language governing
#  permissions and limitations under the License.

import os
import boto
import boto.utils
from sets import Set
import logging
import json
import subprocess
import time
import sys
import datetime
import pwd
import grp
import os
import boto.ec2
import boto.ec2.autoscale
import boto.sqs
import boto.cloudformation

HOST_FILE = '/etc/hosts'
WORKER_FILE = '/opt/deeplearning/workers'
SLEEP_INTERVAL_IN_SECS = 30
SQS_RECEIVE_INTERVAL_IN_SECS = 20
AWS_DL_NODE_TYPE = None
AWS_DL_MASTER_QUEUE = None
AWS_DL_WORKER_QUEUE = None
AWS_DL_SETUP_TIMEOUT = None
AWS_DL_MASTERLAUNCH_TIMEOUT = None
AWS_DL_STACK_ID = None
AWS_DL_WAIT_HANDLE = None
AWS_REGION = None
AWS_DL_ROLE_NAME = None
AWS_DL_DEFAULT_USER = None
EFS_MOUNT = None
CFN_PATH = None

AWS_GPU_INSTANCE_TYPES = [ "g2.2xlarge", "g2.8xlarge", "p2.xlarge", "p2.8xlarge", "p2.16xlarge" ]

'''
Setup Logger and LogLevel
'''
def setup_logging(log_loc='/var/log'):

    log_file = '{}/dl_cfn_setup.log'.format(log_loc)
    LOGGER = logging.getLogger('dl-cfn-setup')
    LOGGER.setLevel(logging.INFO)
    formatter = logging.Formatter('%(asctime)s %(levelname)s: %(filename)s:%(lineno)d %(message)s')
    file_handler = logging.FileHandler(log_file)
    file_handler.setFormatter(formatter)
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)

    LOGGER.addHandler(file_handler)
    LOGGER.addHandler(console_handler)

    return LOGGER

def ping_host(hostname):
    res = os.system("ping -c 1 -w 10 " + hostname)
    return res == 0

def get_gpu_count():
    LOGGER.info('setup_gpu_count')

    instance_type = boto.utils.get_instance_metadata()['instance-type']
    if instance_type not in AWS_GPU_INSTANCE_TYPES:
        LOGGER.info('Not a GPU Instance, number of GPUs: {}'.format(0))
        return 0
    try:
        output = subprocess.check_output(['nvidia-smi', '-L'])
        gpu_count = output.count('\n')
        LOGGER.info("number of GPUs:{}".format(gpu_count))
        return gpu_count
    except subprocess.CalledProcessError as e:
        LOGGER.exception("Error executing nvidia-smi: {}".format(e))
        return 0

def setup_env_variables(master_instance_ip, worker_instance_ips, default_user, efs_mount):
    LOGGER.info("setup_env_variables")

    with open(HOST_FILE, 'a') as hosts, open(WORKER_FILE, 'w+') as w:
        hosts.write("{} deeplearning-master\n".format(master_instance_ip))
        worker_index=1
        for worker_ip in worker_instance_ips:
            hosts.write("{} deeplearning-worker{}\n".format(worker_ip, worker_index) )
            w.write("deeplearning-worker{}\n".format(worker_index))
            worker_index += 1

    gpu_count = get_gpu_count()
    with open("/etc/profile.d/deeplearning.sh", "a") as f:
        num_workers = sum(1 for line in open(WORKER_FILE, "r"))
        f.write("export DEEPLEARNING_WORKERS_COUNT={}\n".format(num_workers))
        f.write("export DEEPLEARNING_WORKERS_PATH={}\n".format(WORKER_FILE))
        f.write("export DEEPLEARNING_WORKER_GPU_COUNT={}\n".format(gpu_count))
        f.write("export EFS_MOUNT={}\n".format(efs_mount))

    #change ownership to ec2-user
    uid = pwd.getpwnam(default_user).pw_uid
    gid = grp.getgrnam(default_user).gr_gid
    os.chown(WORKER_FILE, uid, gid)

    return

'''
wait for asg setup success message from the lambda function
message will be of the format
{"min": 1, "desired": 1, "max": 1, "launched": 1, "status": "success", "asg": "cfn-test-WorkerAutoScalingGroup-1HPKVL6PJEVQS", "event": "asg-setup"}
'''
def wait_until_asg_success(master_queue_name, region, timeout):
    LOGGER.info('wait_until_asg_success on queue_name:{}, timeout:{}'.format(master_queue_name, timeout))
    sqs_con = boto.sqs.connect_to_region(region_name=region)
    sqs_queue = sqs_con.get_queue(queue_name = master_queue_name)
    asg_success_message = {}

    start_time = time.time()
    next_execution_ts = start_time

    while True:
        LOGGER.info('checking autoscaling group success message at {}'.format(datetime.datetime.now()))

        recvd_messages = sqs_con.receive_message(queue=sqs_queue,number_messages=10, visibility_timeout=60)
        LOGGER.info('number of messages received: {}'.format(len(recvd_messages)))
        for msg in recvd_messages:
            msg_body = msg.get_body()
            LOGGER.info('received message with body:{}'.format(msg_body))
            try:
                content = json.loads(msg_body)
                if content is not None and content['event'] == 'asg-setup' and content['status'] == 'success':
                    # http://docs.aws.amazon.com/AWSSimpleQueueService/latest/SQSDeveloperGuide/standard-queues.html#standard-queues-at-least-once-delivery
                    # ignore duplicate message
                    if content['asg'] not in asg_success_message:
                        LOGGER.info('autosclaing_group: {} succeeded at {}'.format(content['asg'], datetime.datetime.now()))
                        asg_success_message[content['asg']] = content
                    else:
                        LOGGER.info('received duplicate sqs message for {} at {}'.format(content['asg'], datetime.datetime.now()))
                sqs_con.delete_message(queue=sqs_queue, message=msg)
            except (TypeError, KeyError) as e:
                LOGGER.exception(e)
                LOGGER.error(msg)
                continue

        if len(asg_success_message) is 2:
            LOGGER.info('status of all autoscaling_groups received')
            break

        next_execution_ts = next_execution_ts + SLEEP_INTERVAL_IN_SECS
        if (next_execution_ts > (start_time + timeout)):
            LOGGER.info('timeout while checking asg status after {} seconds'.format(timeout))
            break

        LOGGER.info('not received all autoscaling group success at {}, WAITING :{}'.format(datetime.datetime.now(), SLEEP_INTERVAL_IN_SECS))
        time.sleep(next_execution_ts - time.time())

    return asg_success_message

def wait_for_worker_setup_message(worker_queue_name, timeout, region):
    LOGGER.info('wait_for_worker_setup_message, worker_queue_name:{}, timeout:{}'.format(worker_queue_name, timeout))
    sqs_con = boto.sqs.connect_to_region(region_name=region)
    sqs_queue = sqs_con.get_queue(queue_name = worker_queue_name)

    start_time = time.time()
    next_execution_ts = start_time

    while True:
        LOGGER.info('checking for worker_setup message at {}'.format(datetime.datetime.now()))
        #visibility_timeout is set to 0, so that other workers can simultaneously act on this message
        recvd_messages = sqs_con.receive_message(queue=sqs_queue,number_messages=10, visibility_timeout=0)
        LOGGER.info('number of messages received: {}'.format(len(recvd_messages)))
        for msg in recvd_messages:
            msg_body = msg.get_body()
            LOGGER.info('received message with body:{}'.format(msg_body))
            try:
                content = json.loads(msg_body)
                if content is not None and content['event'] == 'worker-setup':
                    LOGGER.info('received worker-setup success message: {}'.format(content))
                    # do not delete the message, other workers need to consume this.
                    return content['master-ip'], content['worker-ips']
                else:
                    #don't act on other messages
                    continue
            except (TypeError, KeyError) as e:
                LOGGER.error(e)
                LOGGER.error(msg)
                continue

        next_execution_ts = next_execution_ts + SLEEP_INTERVAL_IN_SECS
        if (next_execution_ts > (start_time + timeout)):
            LOGGER.info('did not receive worker-setup success even after {} seconds'.format(timeout))
            return None

        LOGGER.info('worker setup not complete is not complete at {}'.format(datetime.datetime.now()))
        time.sleep(next_execution_ts - time.time())

    return None

def wait_until_instances_active(autoscaling_groups, timeout, region):
    LOGGER.info('wait_until_instances_active, asgs:{}, timeout:{}'.format(autoscaling_groups, timeout))

    autoscale_con = boto.ec2.autoscale.connect_to_region(region_name=region)
    ec2_con = boto.ec2.connect_to_region(region_name=region)
    start_time = time.time()
    next_execution_ts = start_time
    master_instance_ids = []
    worker_instance_ids = []
    master_instances = {}
    worker_instances = {}
    try:
        # http://boto.cloudhackers.com/en/latest/ref/autoscale.html#boto.ec2.autoscale.group.AutoScalingGroup
        # does not specify how to get the next token for pagination,
        # since there are only 2 groups in our case, we will assume they will be returned in one call
        groups = autoscale_con.get_all_groups(names=autoscaling_groups)

        for asg in groups:
            instance_ids=[]
            for instance in asg.instances:
                if instance.health_status == 'Healthy':
                    instance_ids.append(instance.instance_id)

            if 'master' in asg.name.lower():
                master_instance_ids.extend(instance_ids)
            else:
                worker_instance_ids.extend(instance_ids)
                LOGGER.info('from autoscale, found instances:{} for asg:{}'.format(instance_ids, asg.name))

        LOGGER.info('worker_asg_instane_ids:{}, master_ids:{}'.format(worker_instance_ids, master_instance_ids))
        next_token = None
        pending_instance_ids = master_instance_ids + worker_instance_ids

        while(True):
            LOGGER.info('getting ec2 instance info:{}'.format(pending_instance_ids))
            reservations = ec2_con.get_all_reservations(instance_ids = pending_instance_ids, next_token = next_token)
            next_token = reservations.next_token

            for r in reservations:
                for i in r.instances:
                    if i.state.lower() == 'running':
                        if i.id in master_instance_ids:
                            LOGGER.info('master instance in running state, id:{}, ip:{}'.format(i.id, i.private_ip_address))
                            master_instances[i.id] = i.private_ip_address
                        elif i.id in worker_instance_ids:
                            LOGGER.info('worker instance in running state, id:{}, ip:{}'.format(i.id, i.private_ip_address))
                            worker_instances[i.id] = i.private_ip_address
                            LOGGER.info('worker:{}'.format(worker_instances))
                        pending_instance_ids.remove(i.id)
                    elif i.state.lower() == 'pending':
                        LOGGER.info('instance is still in pending state, instance id:{}'.format(i.id))
                        continue

            next_execution_ts = next_execution_ts + SLEEP_INTERVAL_IN_SECS
            if (len(pending_instance_ids) == 0):
                LOGGER.info('received info of all instances, master: {}, worker: {}'.format(master_instances, worker_instances))
                break
            elif (next_token is not None):
                LOGGER.info('next_token is not None, will continue fetching more instances')
                continue
            elif (next_execution_ts < start_time + timeout):
                LOGGER.error('Reached timeout, pending_instance_ids:{}, next_token:{}'.format(pending_instance_ids, next_token))
                break
            else:
                LOGGER.info('not all instance info is available, pending: {}, waiting for {} seconds'.format(pending_instance_ids, SLEEP_INTERVAL_IN_SECS))
                time.sleep(next_execution_ts - time.time())

        LOGGER.info('master: {}, worker: {}'.format(master_instances, worker_instances))
        return master_instances, worker_instances
    except Exception as e:
        LOGGER.exception(e)
        return ({},{})
'''
This method will send success signal to the wait handle url
its assumed cfn-signal aws cli tool is available on the instance
'''
def send_cfn_success_signal(stack_id, wait_handle_url, aws_region, cfn_path):
    try:
        instance_id = boto.utils.get_instance_metadata()['instance-id']
        cfn_success_signal_command = cfn_path + '/cfn-signal'
        command_args = [cfn_success_signal_command, '--region', aws_region, '--stack', \
        stack_id, '--success', 'true', '--id', instance_id, wait_handle_url]
        LOGGER.info('{} command: {}'.format(cfn_success_signal_command, ' '.join(map(str, command_args))))
        output = subprocess.check_output(command_args)
        LOGGER.info(output)
    except subprocess.CalledProcessError as e:
        LOGGER.exception('FAILED to send cfn-signal')
        sys.exit(1)
    return

'''
waits for a message on SQS for asg setup complete and instances are active.
fetches private ip addresses of the instances and sets up metadata
'''
def setup_worker_metadata(setup_timeout, master_queue_name, stack_id, region):
    LOGGER.info('setup_worker_metadata')

    start_time = time.time()
    asg_setup_messages = wait_until_asg_success(master_queue_name, region, setup_timeout)
    if len(asg_setup_messages) is not 2:
        LOGGER.error('did not receive asg success message for all autoscaling_groups, received only: {}'.format(asg_setup_messages))
        sys.exit(1)

    master_asg_message = None
    worker_asg_message = None
    for key, value in asg_setup_messages.iteritems():
        LOGGER.info('asg success message:{}'.format(value))
        if 'master' in key.lower():
            master_asg_message = value
        else:
            worker_asg_message = value

    timeout = setup_timeout - (time.time() - start_time)
    start_time = time.time()

    (master_instances, worker_instances) = wait_until_instances_active([master_asg_message['asg'], worker_asg_message['asg']], timeout, region)
    LOGGER.info('from wait_until_instances_active, master: {}, worker:{}'.format(master_instances, worker_instances))
    if (len(master_instances) != 1):
        LOGGER.error('expected single master, instead got instance ips:{}', master_instances)
        sys.exit(1)
    master_instance_ip = master_instances.values()[0]
    worker_instance_ips = [master_instance_ip]

    if len(worker_instances) is 0:
        LOGGER.info('no worker is launched, using only master instance as worker')
    else:
        worker_instance_ips.extend(worker_instances.values())

        if (len(worker_instances) != worker_asg_message['launched']):
            LOGGER.error('expected {} number of instances to be running, instead got instance_ids: {}, ips: {}' \
            .format(worker_asg_message['launched'], worker_instances.keys(), worker_instances.values()) )

    worker_instance_ips = sorted(worker_instance_ips)

    return master_instance_ip, worker_instance_ips

def send_worker_setup_msg(worker_queue_name, master_instance_ip, worker_instance_ips, region):
    LOGGER.info('send_worker_setup_msg:{}'.format(send_worker_setup_msg))

    sqs_con = boto.sqs.connect_to_region(region_name=region)
    sqs_queue = sqs_con.get_queue(queue_name = worker_queue_name)

    worker_setup_message={'event' : 'worker-setup'}
    worker_setup_message['master-ip'] = master_instance_ip
    worker_setup_message['worker-ips'] = worker_instance_ips

    LOGGER.info('sending worker-setup message:{}'.format(json.dumps(worker_setup_message)))
    sqs_con.send_message(queue=sqs_queue, message_content=json.dumps(worker_setup_message))

def check_instance_role_availability(role_name, timeout):
    LOGGER.info('check_instance_role_availability, role_name:{}, timeout: {}'.format(role_name, timeout))

    start_time = time.time()
    next_execution_ts = start_time
    while True:
        LOGGER.info('checking presence of instance role: {}, @ :{}'.format(role_name, datetime.datetime.now()))

        try:
            metadata = boto.utils.get_instance_metadata(version='latest',timeout=30, num_retries=5)
            instance_role = metadata['iam']['security-credentials'][role_name]
            # we don't want to log the credentials
            del instance_role['AccessKeyId']
            del instance_role['SecretAccessKey']
            del instance_role['Token']
            LOGGER.info('SUCCESS getting instance role {}'.format(instance_role))
            return True
        except KeyError as e:
            LOGGER.info('FAILED to get instance role: {} @ {}'.format(role_name, datetime.datetime.now()))
            pass
        next_execution_ts = next_execution_ts + SLEEP_INTERVAL_IN_SECS
        if (next_execution_ts > (start_time + timeout)):
            LOGGER.info('TIMEOUT while checking instance role after {} seconds'.format(timeout))
            break

        LOGGER.info('WAITING :{} to get instance_role:{} @ {}'.format(SLEEP_INTERVAL_IN_SECS, role_name, datetime.datetime.now()))
        time.sleep(next_execution_ts - time.time())
    return False

LOGGER = setup_logging()
def main():
    LOGGER.info("main")

    try:
        AWS_DL_NODE_TYPE = os.environ["AWS_DL_NODE_TYPE"]
        AWS_DL_MASTER_QUEUE = os.environ['AWS_DL_MASTER_QUEUE']
        AWS_DL_WORKER_QUEUE = os.environ['AWS_DL_WORKER_QUEUE']
        AWS_DL_WAITCONDITION_TIMEOUT = float(os.environ['AWS_DL_WAITCONDITION_TIMEOUT'])
        AWS_DL_MASTERLAUNCH_TIMEOUT = float(os.environ['AWS_DL_MASTERLAUNCH_TIMEOUT'])
        AWS_DL_STACK_ID = os.environ['AWS_DL_STACK_ID']
        AWS_DL_WAIT_HANDLE = os.environ['AWS_DL_WAIT_HANDLE']
        AWS_DL_ROLE_NAME = os.environ['AWS_DL_ROLE_NAME']
        AWS_DL_DEFAULT_USER = os.environ['AWS_DL_DEFAULT_USER']
        AWS_REGION = os.environ['AWS_REGION']
        EFS_MOUNT = os.environ['EFS_MOUNT']
        CFN_PATH = os.environ['CFN_PATH']

        LOGGER.info('AWS_DL_NODE_TYPE:{}\n AWS_DL_MASTER_QUEUE:{}\n AWS_DL_WORKER_QUEUE:{}\n AWS_DL_WAITCONDITION_TIMEOUT:{}\n, AWS_DL_MASTERLAUNCH_TIMEOUT:{}\n AWS_DL_STACK_ID:{}\n \
            AWS_DL_WAIT_HANDLE:{}\n AWS_DL_ROLE_NAME:{}\n AWS_REGION:{}, AWS_DL_DEFAULT_USER:{}, EFS_MOUNT:{}, CFN_PATH:{}\n'.format(AWS_DL_NODE_TYPE, AWS_DL_MASTER_QUEUE, AWS_DL_WORKER_QUEUE, \
            AWS_DL_WAITCONDITION_TIMEOUT, AWS_DL_MASTERLAUNCH_TIMEOUT, AWS_DL_STACK_ID, AWS_DL_WAIT_HANDLE, AWS_DL_ROLE_NAME, AWS_REGION, AWS_DL_DEFAULT_USER, EFS_MOUNT, CFN_PATH)
        )

        # we want to make sure we finish before the timeout expires
        setup_timeout = AWS_DL_WAITCONDITION_TIMEOUT - AWS_DL_MASTERLAUNCH_TIMEOUT
        start_time = time.time()
        check_instance_role_availability(AWS_DL_ROLE_NAME, setup_timeout)
        setup_timeout = setup_timeout - (time.time() - start_time)

        # get master ips
        if (AWS_DL_NODE_TYPE.lower() == 'master'):
            master_instance_ip, worker_instance_ips = setup_worker_metadata(setup_timeout, AWS_DL_MASTER_QUEUE, AWS_DL_STACK_ID, AWS_REGION)
            setup_env_variables(master_instance_ip, worker_instance_ips, AWS_DL_DEFAULT_USER, EFS_MOUNT)
            send_worker_setup_msg(AWS_DL_WORKER_QUEUE, master_instance_ip, worker_instance_ips, AWS_REGION)
            send_cfn_success_signal(AWS_DL_STACK_ID, AWS_DL_WAIT_HANDLE, AWS_REGION, CFN_PATH)

        elif (AWS_DL_NODE_TYPE.lower() == 'worker'):
            master_instance_ip, worker_instance_ips = wait_for_worker_setup_message(AWS_DL_WORKER_QUEUE, setup_timeout, AWS_REGION)
            if master_instance_ip is None or worker_instance_ips is None:
                LOGGER.error('FAILED worker metadata setup : master_ip:{}, worker_ips:{}'.format(master_instance_ip, worker_instance_ips))
                sys.exit(1)
            setup_env_variables(master_instance_ip, worker_instance_ips, AWS_DL_DEFAULT_USER, EFS_MOUNT)
        else:
            LOGGER.error('unknown node type: {}'.format(AWS_DL_NODE_TYPE))
            sys.exit(1)

    except Exception as e:
        LOGGER.exception(e)
        sys.exit(1)

if  __name__ =='__main__':
    main()
