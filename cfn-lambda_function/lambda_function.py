#  Copyright 2018 Amazon.com, Inc. or its affiliates. All Rights Reserved.
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

from __future__ import print_function

import json
import os
import boto3
import collections

print('Loading function')
ASGInstanceCount = collections.namedtuple('ASGInstanceCount', ['min', 'desired', 'max', 'launched'])

def lambda_handler(event, context):
    # print("Received event: " + json.dumps(event, indent=2))
    message = json.loads(event['Records'][0]['Sns']['Message'])
    # print("From SNS: " + event['Records'][0]['Sns']['Message'])
    # print('AWS_STACK_ID: ' + os.environ['AWS_STACK_ID'])
    if message['Event']:
        print('EVENT: ', message['Event'])
        return eval(get_handler(message['Event']))(message)
    else:
        return do_nothing(message)

    return message

def get_handler(Event):
    return {
        'autoscaling:EC2_INSTANCE_LAUNCH': 'on_instance_launch',
        'autoscaling:EC2_INSTANCE_LAUNCH_ERROR': 'on_instance_launch_error',
        'autoscaling:EC2_INSTANCE_TERMINATE': 'on_instance_terminate',
        'autoscaling:EC2_INSTANCE_TERMINATE_ERROR': 'on_instance_terminate_error',
        'autoscaling:TEST_NOTIFICATION' : 'do_nothing'
    }[Event]

def do_nothing(message):
    print('do_nothing')
    print("Unknown Event. Received message: " + json.dumps(message, indent=2))
    return

def send_asg_success(status, asg, asg_instance_counts):
     sqs_url = os.environ['AWS_DL_MASTER_SQS_URL']
     print("sqs_url: ", sqs_url)
     sqs_con = boto3.client('sqs')
     msg_dict = asg_instance_counts._asdict()
     msg_dict['status'] = status.lower()
     msg_dict['asg'] = asg
     msg_dict['event'] = 'asg-setup'
 
     print('sending message to sqs:', json.dumps(msg_dict))
     sqs_con.send_message(QueueUrl=sqs_url, MessageBody=json.dumps(msg_dict))
     return

'''
    get various instance counts associated with the asg
'''
def get_instance_count(autoscaling_group_name):
    print('get_instance_count')

    autoscale_con = boto3.client('autoscaling')
    
    asg = autoscale_con.describe_auto_scaling_groups(AutoScalingGroupNames=[autoscaling_group_name])['AutoScalingGroups'][0]
    num_instances_healthy = 0

#   TODO: check if pagination needs to be handled for asg.instances
    for each_instance in asg['Instances']:
        '''         
        we will only consider instances that are inService or are in Pending state 
        http://docs.aws.amazon.com/AWSEC2/latest/UserGuide/ec2-instance-lifecycle.html
        since this lambda function is expected to run during stack creation, we'll ignore the 
        case where the User could go and Stop the Instance and can move the instance state to 'Pending'
        '''
        if each_instance['LifecycleState'] == 'InService' and each_instance['HealthStatus'] == 'Healthy':
            num_instances_healthy += 1
        elif each_instance['LifecycleState'] == 'Pending' and each_instance['HealthStatus'] == 'Healthy':
            num_instances_healthy += 1
        else:
            continue    
    
    asg_instance_counts = ASGInstanceCount(min=asg['MinSize'], max=asg['MaxSize'], desired=asg['DesiredCapacity'], launched=num_instances_healthy)
    print(asg_instance_counts._asdict())
    return asg_instance_counts

def on_instance_launch(message):
    print('on_instance_launch')

    autoscaling_group_name = message['AutoScalingGroupName']
    availability_zone = message['Details']['Availability Zone']
    start_time = message['StartTime']
    instance_id = message['EC2InstanceId']
    request_id = message['RequestId']

    if autoscaling_group_name and 'WorkerAutoScalingGroup' in autoscaling_group_name:
        autoscaling_group = 'WorkerAutoScalingGroup'
    elif autoscaling_group_name and 'MasterAutoScalingGroup' in autoscaling_group_name:
        autoscaling_group = 'MasterAutoScalingGroup'
    else:
        print('Unknown AutoScaling group,message :',message)
        return
    
    print('AutoScalingGroupName: ', autoscaling_group_name, ', EC2InstanceId: ', instance_id, \
    ', Availability Zone: ', availability_zone, ', Instance StartTime: ', start_time, ', RequestId: ',request_id)
    
    logical_resource_id = None
    asg_instance_counts = get_instance_count(autoscaling_group_name)

    if asg_instance_counts.launched == asg_instance_counts.desired:
        print('Launched desired number of instances:', asg_instance_counts.launched)
        send_asg_success('SUCCESS', autoscaling_group_name, asg_instance_counts)

        if autoscaling_group is 'MasterAutoScalingGroup':
            cfn_con = boto3.client('cloudformation')
            print('Sending cfn-signal SUCCESS to:', autoscaling_group_name, 'with instance Id: ', instance_id)
            try:
                cfn_con.signal_resource(StackName=os.environ['AWS_DL_STACK_ID'], LogicalResourceId=autoscaling_group, \
                    UniqueId=instance_id,Status='SUCCESS')
            except Exception as e:
                print('exception sending cfn-signal: ', e.message)
        else:
            autoscale_con = boto3.client('autoscaling')
            print('Suspending ReplaceUnhealthy processes for the asg: ', autoscaling_group_name)
            autoscale_con.suspend_processes(AutoScalingGroupName=autoscaling_group_name, ScalingProcesses=['ReplaceUnhealthy'])

    return

'''
suspend autoscaling policy
change desired capacity
send success message to sqs

'''
def on_instance_launch_error(message):
    print('on_instance_launch_error')

    autoscaling_group_name = message['AutoScalingGroupName']
    availability_zone = message['Details']['Availability Zone']
    start_time = message['StartTime']
    instance_id = message['EC2InstanceId']
    request_id = message['RequestId']

    print('AutoScalingGroupName: ', autoscaling_group_name, ', EC2InstanceId: ', instance_id, \
    ', Availability Zone: ', availability_zone, ', Instance StartTime: ', start_time, ', RequestId: ',request_id)
    print('StatusCode: ', message['StatusCode'],  'StatusMessage: ', message['StatusMessage'])
    
    autoscale_con = boto3.client('autoscaling')
    asg_instance_counts = get_instance_count(autoscaling_group_name)

    '''
    change desired capacity and suspend processes only if we have atleast the min_size requested
    '''
    if asg_instance_counts.launched >= asg_instance_counts.min:
        print('setting desired capacity of asg: ', autoscaling_group_name, ' to number of Healthy instances: ', asg_instance_counts.launched)
        autoscale_con.set_desired_capacity(AutoScalingGroupName=autoscaling_group_name, DesiredCapacity=asg_instance_counts.launched)
        print('Suspending ReplaceUnhealthy processes for the asg: ', autoscaling_group_name)
        autoscale_con.suspend_processes(AutoScalingGroupName=autoscaling_group_name, ScalingProcesses=['ReplaceUnhealthy'])
        print('sending worker asg setup message complete to sqs')
        send_asg_success('SUCCESS', autoscaling_group_name, asg_instance_counts)
 
    return

'''
'''
def on_instance_terminate(message):
    print('on_instance_terminate')

    autoscaling_group_name = message['AutoScalingGroupName']
    availability_zone = message['Details']['Availability Zone']
    start_time = message['StartTime']
    instance_id = message['EC2InstanceId']
    request_id = message['RequestId']

    print('AutoScalingGroupName: ', autoscaling_group_name, ', EC2InstanceId: ', instance_id, \
    ', Availability Zone: ', availability_zone, ', Instance StartTime: ', start_time, ', RequestId: ',request_id)

    return

def on_instance_terminate_error():
    print('on_instance_terminate_error')

    autoscaling_group_name = message['AutoScalingGroupName']
    availability_zone = message['Details']['Availability Zone']
    start_time = message['StartTime']
    instance_id = message['EC2InstanceId']
    request_id = message['RequestId']

    print('AutoScalingGroupName: ', autoscaling_group_name, ', EC2InstanceId: ', instance_id, \
    ', Availability Zone: ', availability_zone, ', Instance StartTime: ', start_time, ', RequestId: ',request_id)

    return
