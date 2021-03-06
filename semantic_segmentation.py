import numpy as np
import scipy.misc
import scipy.io
import tensorflow as tf
from load_images import Data
from datetime import datetime
import pickle as pkl

def _conv_layer(input, weights, bias):
  '''convolution layer'''
  conv = tf.nn.conv2d(input, tf.Variable(weights, dtype=tf.float32),
    strides=(1, 1, 1, 1), padding='SAME')
  return tf.nn.bias_add(conv, tf.Variable(bias, dtype=tf.float32))

def _pool_layer(input):
  '''pool layer'''
  return tf.nn.max_pool(input, ksize=(1, 2, 2, 1),
    strides=(1, 2, 2, 1), padding='SAME')


##########################################
#########LOAD PRE-TRAINED NETWORK#########
##########################################

#Network architecture
layers = (
      'conv1_1', 'relu1_1', 'conv1_2', 'relu1_2', 'pool1',

      'conv2_1', 'relu2_1', 'conv2_2', 'relu2_2', 'pool2',

      'conv3_1', 'relu3_1', 'conv3_2', 'relu3_2', 'conv3_3',
      'relu3_3', 'conv3_4', 'relu3_4', 'pool3',

      'conv4_1', 'relu4_1', 'conv4_2', 'relu4_2', 'conv4_3',
      'relu4_3', 'conv4_4', 'relu4_4', 'pool4',

      'conv5_1', 'relu5_1', 'conv5_2', 'relu5_2', 'conv5_3',
      'relu5_3', 'conv5_4', 'relu5_4', 'pool5',
      
      'fc6', 'relu6',
      
      'fc7', 'relu7',
  )
  

#Load vgg network weights from .mat file
VGG_PATH = 'imagenet-vgg-verydeep-19.mat'
data = scipy.io.loadmat(VGG_PATH)
weights = data['layers'][0]

#Load mean pixel values so we can center pictures
#(This is done on the VGG paper as well)
mean = data['normalization'][0][0][0]
mean_pixel = np.mean(mean, axis=(0, 1))

#Keep track of all the network layers so we can extract output at arbitrary locations.
net = {}

#Placeholder for the image
input_image = tf.placeholder(tf.float32, shape=(None, None, None, 3))

#Center image
centered_image = tf.sub(input_image, tf.constant(mean_pixel, dtype=tf.float32))
current = centered_image

for i, name in enumerate(layers):
  kind = name[:4]
  if kind == 'conv' or kind == 'fc':
    kernels, bias = weights[i][0][0][0][0]
    # matconvnet: weights are [width, height, in_channels, out_channels]
    # tensorflow: weights are [height, width, in_channels, out_channels]
    kernels = np.transpose(kernels, (1, 0, 2, 3))
    bias = bias.reshape(-1)
    current = _conv_layer(current, kernels, bias)
  elif kind == 'relu':
    current = tf.nn.relu(current)
  elif kind == 'pool':
    current = _pool_layer(current)
    
  net[name] = current

  
##########################################
#########ADD DECONVOLUTION LAYERS#########
##########################################

#Deconvolutions for up-sampling
  
deconv8 = tf.nn.conv2d_transpose(
  value=net['pool3'],
  filter=tf.Variable(tf.truncated_normal(shape=(8, 8, 1, 256), mean=1.0)),
  output_shape=tf.pack((tf.shape(net['pool3'])[0],tf.shape(input_image)[1],tf.shape(input_image)[2],1)),
  strides=(1, 8, 8, 1), padding='SAME') + tf.Variable(tf.truncated_normal(shape=(1,),stddev=0.1), dtype=tf.float32)
  
deconv16 = tf.nn.conv2d_transpose(
  value=net['pool4'],
  filter=tf.Variable(tf.truncated_normal(shape=(16, 16, 1, 512),mean=1.0)),
  output_shape=tf.pack((tf.shape(net['pool4'])[0],tf.shape(input_image)[1],tf.shape(input_image)[2],1)),
  strides=(1, 16, 16, 1), padding='SAME') + tf.Variable(tf.truncated_normal(shape=(1,),stddev=0.1), dtype=tf.float32)

deconv32 = tf.nn.conv2d_transpose(
  value=net['relu7'],
  filter=tf.Variable(tf.truncated_normal(shape=(32, 32, 1, 512), mean=1.0)),
  output_shape=tf.pack((tf.shape(net['relu7'])[0],tf.shape(input_image)[1],tf.shape(input_image)[2],1)),
  strides=(1, 32, 32, 1), padding='SAME') + tf.Variable(tf.truncated_normal(shape=(1,),stddev=0.1), dtype=tf.float32)
  
#Concatenate them, one deconvolution per channel
deconvs = tf.concat(3,(deconv8, deconv16, deconv32))

#One last convolution to rule them all
conv    = tf.nn.conv2d(deconvs, tf.Variable(tf.truncated_normal(shape=(1,1,3,21), mean=1.0), dtype=tf.float32),
  strides=(1,1,1,1), padding="SAME") + tf.Variable(tf.truncated_normal(shape=(21,),stddev=0.1), dtype=tf.float32)
  
#Batch normalization
from batch_norm import batch_norm
bn = batch_norm(conv, scale=True, is_training=True)
  
#Network estimate
exp = tf.exp(bn)
norm = tf.reduce_sum(exp, reduction_indices=3, keep_dims=True)
y_hat = tf.div(exp, norm)

##########################################
########TRAIN DECONVOLUTION LAYERS########
##########################################

#Test data
indices = tf.placeholder(tf.int64, shape=(None,None,None))
targets = tf.one_hot(indices=indices, depth=21, on_value=1.0, off_value=0.0, axis=-1)

#Loss function (cross-entropy)
loss = -tf.reduce_sum(tf.mul(targets,tf.log(tf.clip_by_value(y_hat,1e-10,1.0))))
loss_summary = tf.scalar_summary("cross_entropy_loss/", loss)

#Adamame for optimization
train_step = tf.train.AdamOptimizer(1e-4).minimize(loss)

# Test time segmentation
se_hat = tf.argmax(conv, 3)

#Training time in tensor-ville...

#Saver object
saver = tf.train.Saver()

# #Step
# try:
#   with open("Model_data/step.pkl","rb") as f:
#     step = pkl.load(f)
# except:
#   step = 0

# data_set = Data()
# with tf.Session() as sess:
  
#   train_writer = tf.train.SummaryWriter("./Model_data/train/", sess.graph)
#   test_writer = tf.train.SummaryWriter("./Model_data/test/")
#   summary_op = tf.merge_all_summaries()
  
#   try:
#     saver.restore(sess, "Model_data/model.ckpt")
#     print("Model restored.")
#   except:
#     sess.run(tf.initialize_all_variables())
#     print("Model initialized.")
  
#   print "Training"
#   for _ in range(100):
#     step += 1
  
#     #Fetch a batch
#     batch = data_set.get_batch(20)
#     feed_dict={input_image:batch[0], indices:batch[1]}
    
#     with tf.device("/gpu:0"):
#       train_step.run(feed_dict=feed_dict)
    
#     if step%100 == 0:
#       print step, datetime.now()
      
#       save_path = saver.save(sess, "Model_data/model.ckpt")
#       print("Model saved in file: %s" % save_path)
      
#     if step%5 == 0:
#       print step, datetime.now()
      
#       # Test
#       test_batch = data_set.get_batch(20, train=False)
#       test_feed_dict={input_image:test_batch[0], indices:test_batch[1]}
      
#       with tf.device("/cpu:0"):
#         train_summary_str = summary_op.eval(feed_dict=feed_dict)
#         train_writer.add_summary(train_summary_str, step)
#         train_writer.flush()
        
#         test_summary_str = summary_op.eval(feed_dict=test_feed_dict)
#         test_writer.add_summary(test_summary_str, step)
#         test_writer.flush()
        
#     if step%100==0:
#       #Sample image
#       im_id, im, se = Data.get_image("2011_001967")
      
#       # Semantic segmentation
#       with tf.device("/gpu:0"):
#         net_output = se_hat.eval(feed_dict={input_image:[im], indices:[se]})[0,:,:]
        
#       Data.save_side2side(im_id, net_output, title="examples/semantic_segmentation_example_{step}.png".format(step=step))
        
#       # Heatmap
#       # heat = deconv32.eval(feed_dict={input_image:[im], indices:[se]})[0,:,:,0]
#       # heat = 255*(heat/np.max(heat))
#       # scipy.misc.imsave("examples/heat.png",heat)
            
# print step, datetime.now()

# #Save step
# with open("Model_data/step.pkl","wb") as f:
#   pkl.dump(step,f)


#Save a few more examples
# with tf.Session() as sess:
#   saver.restore(sess, "Model_data/model.ckpt")
#   print("Model restored.")
  
#   Images = []
#   for _ in range(10):
#     im_id, im, se = Data.get_image()
#     Images.append((im_id,im,se))
  
#   with tf.device("/gpu:0"):
#     for im_id, im, se in Images:
#       net_output = se_hat.eval(feed_dict={input_image:[im], indices:[se]})[0,:,:]
#       Data.save_side2side(im_id, net_output, title="examples/semantic_segmentation_more_examples_{im_id}.png".format(im_id=im_id))

#Compute pixel accuracy

correct = tf.to_float(tf.equal(tf.to_int64(indices), se_hat))
pixel_acc = tf.reduce_mean(correct)
all_counts = tf.add(indices,1)
correct_counts = tf.mul(correct,tf.to_float(tf.add(indices,1)))

Pixel = 0
All, Correct = np.zeros(21), np.zeros(21)

data_set = Data()
with tf.Session() as sess:
  saver.restore(sess, "Model_data/model.ckpt")
  print("Model restored.")
  
  with tf.device("/gpu:0"):
    
    for n in range(10):
      batch = data_set.get_batch(20)
      feed_dict={input_image:batch[0], indices:batch[1]}
      pxl_acc = pixel_acc.eval(feed_dict=feed_dict)
      a_classes = np.bincount(all_counts.eval(feed_dict=feed_dict).flatten().astype(np.int))
      c_classes = np.bincount(correct_counts.eval(feed_dict=feed_dict).flatten().astype(np.int))
      
      Pixel = float(n*Pixel + pxl_acc)/(n+1)
      print Pixel
      for i in range(len(c_classes)):
        if i==0: continue
        
        All[i-1] += a_classes[i]
        Correct[i-1] += c_classes[i]
     

pxl_acc_class = {i:float(Correct[i])/max(1,All[i]) for i in range(len(Correct))}
 
print "Pixel Accuracy: ", Pixel
print "Per-class pizel accuracy: ", pxl_acc_class