from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

from datetime import datetime
import sys
import os.path
sys.path.insert(0, os.path.dirname(__file__) + '/models/tutorials/image/cifar10/')

import cifar10
import re
import time
import argparse
import numpy as np
from six.moves import xrange  # pylint: disable=redefined-builtin
import tensorflow as tf


FLAGS = tf.app.flags.FLAGS

tf.app.flags.DEFINE_integer('max_steps', 1000000,
                            """Number of batches to run.""")
tf.app.flags.DEFINE_string("ps_hosts", "",
                           "Comma-separated list of hostname:port pairs")
tf.app.flags.DEFINE_string("worker_hosts", "",
                           "Comma-separated list of hostname:port pairs")

tf.app.flags.DEFINE_string("job_name", "", "One of 'ps', 'worker'")

tf.app.flags.DEFINE_integer("task_index", 0, "Index of task within the job")

tf.app.flags.DEFINE_string('train_dir', '/tmp/cifar10_train',
                           """Directory where to write event logs """
                           """and checkpoint.""")

def main(_):

    class _LoggerHook(tf.train.SessionRunHook):
        """Logs loss and runtime."""

        def begin(self):
            self._step = -1

        def before_run(self, run_context):
            self._step += 1
            self._start_time = time.time()
            return tf.train.SessionRunArgs(loss)  # Asks for loss value.

        def after_run(self, run_context, run_values):
            duration = time.time() - self._start_time
            loss_value = run_values.results
            if self._step % 10 == 0:
                num_examples_per_step = FLAGS.batch_size
                examples_per_sec = num_examples_per_step / duration
                sec_per_batch = float(duration)

                format_str = ('%s: step %d, loss = %.2f (%.1f examples/sec; %.3f '
                            'sec/batch)')
                print (format_str % (datetime.now(), self._step, loss_value,
                                    examples_per_sec, sec_per_batch))
    ps_hosts = FLAGS.ps_hosts.split(",")
    worker_hosts = FLAGS.worker_hosts.split(",")

    # Create a cluster from the parameter server and worker hosts.
    cluster = tf.train.ClusterSpec({"ps": ps_hosts, "worker": worker_hosts})

    # Create and start a server for the local task.
    server = tf.train.Server(cluster,
                            job_name=FLAGS.job_name,
                            task_index=FLAGS.task_index)

    if FLAGS.job_name == "ps":
        server.join()
    elif FLAGS.job_name == "worker":

        # Assigns ops to the local worker by default.
        with tf.device(tf.train.replica_device_setter(
            worker_device="/job:worker/task:%d" % FLAGS.task_index,
            cluster=cluster)):

            global_step = tf.contrib.framework.get_or_create_global_step()

            # Get images and labels for CIFAR-10.
            images, labels = cifar10.distorted_inputs()

            # Build inference Graph.
            logits = cifar10.inference(images)

            # Build the portion of the Graph calculating the losses. Note that we will
            # assemble the total_loss using a custom function below.
            loss = cifar10.loss(logits, labels)

            # Build a Graph that trains the model with one batch of examples and
            # updates the model parameters.
            train_op = cifar10.train(loss,global_step)

        # The StopAtStepHook handles stopping after running given steps.
        hooks=[tf.train.StopAtStepHook(last_step=FLAGS.max_steps), _LoggerHook()]

        # The MonitoredTrainingSession takes care of session initialization,
        # restoring from a checkpoint, saving to a checkpoint, and closing when done
        # or an error occurs.
        with tf.train.MonitoredTrainingSession(master=server.target,
                                                is_chief=(FLAGS.task_index == 0),
                                                checkpoint_dir=FLAGS.train_dir,
                                                save_checkpoint_secs=60,
                                                hooks=hooks) as mon_sess:
            while not mon_sess.should_stop():
                # Run a training step asynchronously.
                # See `tf.train.SyncReplicasOptimizer` for additional details on how to
                # perform *synchronous* training.
                # mon_sess.run handles AbortedError in case of preempted PS.
                mon_sess.run(train_op)

if __name__ == "__main__":
    if tf.gfile.Exists(FLAGS.train_dir) is False:
        tf.gfile.MakeDirs(FLAGS.train_dir)
    tf.app.run()
