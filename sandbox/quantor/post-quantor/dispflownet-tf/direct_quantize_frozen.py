import sys
import os
import time
import logging
import argparse
import numpy as np
from dispnet import input_pipeline
from util import ft3d_filenames
from tensorflow.python.framework import graph_util
import tensorflow as tf
import tfquantor as qg

INPUT_SIZE = (384, 768, 3)

def load_graph_def(pb):
  with tf.gfile.GFile(pb, "rb") as f:
    graph_def = tf.GraphDef()
    graph_def.ParseFromString(f.read())
  return graph_def


if __name__ == '__main__':
  parser = argparse.ArgumentParser()
  parser.add_argument("--data_path", dest="dataset_path", required=True, type=str,
      metavar="FILE", help='path to FlyingThings3D dataset')
  parser.add_argument("--batch_size", dest="batch_size", default=4, type=int, help='batch size')
  parser.add_argument("--num_batches", dest="num_batches", default=1000, type=int, help='number of batches')
  parser.add_argument("--log_step", dest="log_step", default=100, type=int, help='log step size')
  parser.add_argument("--frozen_model", dest="frozen_model", required=True, type=str,
      metavar="FILE", help='input frozen model')
  parser.add_argument("--input_nodes", dest="input_nodes", required=True, type=str, help="input nodes (colon-seperated)")
  parser.add_argument("--output_node", dest="output_node", required=True, type=str, help="output node")
  parser.add_argument("--output_dir", dest="output_dir", required=True, type=str, help="output directory")

  args = parser.parse_args()

  input_node_name = args.input_nodes.split(':')
  assert len(input_node_name) == 2

  ft3d_dataset = ft3d_filenames(args.dataset_path)
  l_image, r_image, target = input_pipeline(ft3d_dataset['TRAIN'], input_size=INPUT_SIZE, batch_size=args.batch_size, shuffle=True)

  target_holder = tf.placeholder(tf.float32, [None, None, None, None])
  prediction_holder = tf.placeholder(tf.float32, [None, None, None, None])
  height, width, _ = INPUT_SIZE
  resize_target = tf.image.resize_nearest_neighbor(target_holder, [height / 2, width / 2])
  loss = tf.reduce_mean(tf.cast(tf.abs(resize_target - prediction_holder), tf.float32))

  graph_def = load_graph_def(args.frozen_model)

  g = tf.Graph()
  with tf.Session(graph=g) as sess:
    tf.import_graph_def(graph_def, name='')
    quantized_eval_graph = qg.create_direct_quant_eval_graph(g, inplace=False, extra_quantize_option='all')

  gpu_options = tf.GPUOptions(allow_growth=True)
  with tf.Session(config=tf.ConfigProto(gpu_options=gpu_options)) as sess:

    tf.import_graph_def(graph_def, name='')
    graph = sess.graph

    qg.create_direct_quant_training_graph(graph, inplace=True, extra_quantize_option='all')

    sess.run(tf.global_variables_initializer())
    sess.run(tf.local_variables_initializer())
    coord = tf.train.Coordinator()
    threads = tf.train.start_queue_runners(sess=sess, coord=coord)
    saver = tf.train.Saver()

    x_l = graph.get_tensor_by_name('{}:0'.format(input_node_name[0]))
    x_r = graph.get_tensor_by_name('{}:0'.format(input_node_name[1]))
    y = graph.get_tensor_by_name('{}:0'.format(args.output_node))

    total_error = 0
    for i in range(args.num_batches):
      cur_step = i + 1
      l_npy, r_npy, target_npy = sess.run([l_image, r_image, target])
      y_npy = sess.run(y, feed_dict={x_l: l_npy, x_r: r_npy})
      err = sess.run(loss, feed_dict={target_holder: target_npy, prediction_holder: y_npy})
      total_error += err

      if cur_step % args.log_step == 0:
        print('batch #{}, average training error = {:.6f}'.format(cur_step, total_error / float(cur_step)))

    print('Training error = {:.6f}'.format(total_error / args.num_batches))

    coord.request_stop()
    coord.join(threads)

    freeze_graph_def = graph_util.convert_variables_to_constants(sess, quantized_eval_graph.as_graph_def(), [args.output_node])
    with open(os.path.join(args.output_dir, 'frozen.pb'), 'wb') as f:
      f.write(freeze_graph_def.SerializeToString())
