# python3
# Make this standard template for testing and training
from __future__ import division
from __future__ import print_function

import sys
import os
import shutil
sys.path.append( '%s/gcn' % os.path.dirname(os.path.realpath(__file__)) )

import time
import random
import scipy.io as sio
import numpy as np
import scipy.sparse as sp
from multiprocessing import Queue
from copy import deepcopy
from scipy.stats.stats import pearsonr, linregress

import tensorflow as tf
from collections import deque
import warnings
warnings.filterwarnings('ignore')

import pdb
import matplotlib
matplotlib.use('agg')
import matplotlib.pyplot as plt


from gcn.utils import *
# Settings (FLAGS)
from runtime_config import flags, FLAGS
from heuristics import *

# Dummy functions to ease debugging
def get_critic_d_par(cr_idx=0, w_idx=0):
    return dqn_agent_d.critic[cr_idx].trainable_weights[w_idx]

def get_critic_par(w_idx=0):
    return dqn_agent.critic.trainable_weights[w_idx]

def set_critic_d_weights(critic_d, trainable_weights):
    for j, cr in enumerate(critic_d):
        cr.set_weights(trainable_weights)

def avg_grad(adj_0, grads, t=10):
    for _ in range(t):
        for i, row in enumerate(adj_0.toarray()):
            nbrs = np.where(row)[0]
            grad_i = grads[i]
            for nbr in nbrs:
                grad_i += grads[nbr]
            grad_i /= (nbrs.shape[-1]+1)
    return grads


def grad_avg_experiment(grad_distr, grad_central, T=10, verbose=False):
    difference = []
    for t in range(T):
        grad_distr_ = copy.deepcopy(grad_distr)
        if verbose:
            print(f"t={t}")
            print(f"We want to approximate:\n {grad_central}")
            print('=====')
        pre_fro = np.linalg.norm(grad_central - grad_distr_[0])
        if verbose:
            print(f"Before averaging:\n {grad_distr_[0]},\t Frobenius norm of difference: {pre_fro}")
            print('=====')
        grads_avg = avg_grad(adj_0, grad_distr_, t=t)
        post_fro = np.linalg.norm(grad_central - grads_avg[0])
        if verbose:
            print(f"After averaging:\n {grad_distr_[0]},\t Frobenius norm of difference: {post_fro}")
            print('=====')
        difference.append((t, post_fro))
    return difference

flags.DEFINE_string('test_datapath', './data/ER_Graph_Uniform_NP20_test', 'test dataset')
flags.DEFINE_integer('ntrain', 1, 'Number of units in hidden layer 1.')
flags.DEFINE_integer('nvalid', 100, 'Number of outputs.')
flags.DEFINE_integer('nprobs', 1, 'Number of problems (graphs) to solve')
from mwis_gcn_call_twin import DQNAgent, DQNAgentDistr
dqn_agent = DQNAgent(FLAGS, 5000)

# test data path
data_path = FLAGS.datapath
test_datapath = FLAGS.test_datapath
val_mat_names = sorted(os.listdir(data_path), key=lambda x: int(x.split('_')[1][1:]))  # Sort by num nodes
val_mat_names = val_mat_names[:FLAGS.nprobs]

test_mat_names = sorted(os.listdir(test_datapath))

# Some preprocessing
noout = min(FLAGS.diver_num, FLAGS.diver_out) # number of outputs
time_limit = FLAGS.timeout  # time limit for searching
backoff_thresh = 1 - FLAGS.backoff_prob

num_supports = 1 + FLAGS.max_degree
nsr = np.power(10.0, -FLAGS.snr_db/20.0)

from directory import create_result_folder, find_model_folder
model_origin = find_model_folder(FLAGS, 'dqn')
critic_origin = find_model_folder(FLAGS, 'critic')

# use gpu 0
os.environ['CUDA_VISIBLE_DEVICES'] = str(0)

# Initialize session
config = tf.compat.v1.ConfigProto()
config.gpu_options.allow_growth = True
# TMP comment out
# try:
#     dqn_agent.load_critic(critic_origin)
# except:
#     print("Unable to load {}".format(critic_origin))

try:
    dqn_agent.load(model_origin)
except:
    print("Unable to load {}".format(model_origin))

best_IS_vec = []
loss_vec = []
results = pd.DataFrame([], columns=["data", "p"])
csvname = "./output/{}_{}_train_foo.csv".format(model_origin.split('/')[-1], test_datapath.split('/')[-1])

epislon_reset = [5, 10, 15, 20]
epislon_val = 1.0
eval_size = FLAGS.nvalid
n_samples = FLAGS.ntrain
best_ratio = 1.0
last_ap = 1.0
batch_size = 1
tr_best = 0

for epoch in range(FLAGS.epochs):
    losses = []
    losses_crt = []
    cnt = 0
    f_ct = 0
    q_totals = []
    p_ratios = []
    z_means = []
    p_corrs = []
    newtime = time.time()
    for id in np.random.permutation(len(val_mat_names)):
        best_IS_num = -1
        mat_contents = sio.loadmat(data_path + '/' + val_mat_names[id])
        adj_0 = mat_contents['adj']
        nn = adj_0.shape[0]
        wts = np.random.uniform(0, 1, size=(nn, 1))
        start_time = time.time()
        _, greedy_util = greedy_search(adj_0, wts)
        # Distributed
        dqn_agent_d = DQNAgentDistr(FLAGS, memory_size=5000, num_critic=nn)  # distributed hence _d
        set_critic_d_weights(dqn_agent_d.critic, dqn_agent.critic.trainable_weights)
        #import pdb; pdb.set_trace()

        state, zs_t = dqn_agent.foo_train(adj_0, wts, train=True)
        mwis, ss_util = dqn_agent.solve_mwis(adj_0, wts, train=False, grd=greedy_util)
        zn_t = 0.5 + (zs_t - tf.reduce_mean(zs_t))
        ind_vec, apu_avg = dqn_agent.predict_train(adj_0, zs_t, state, n_samples=n_samples)

        state_d, zs_t_d = dqn_agent_d.foo_train(adj_0, wts, train=True)
        ind_vec_d, apu_avg_d = dqn_agent_d.predict_train(adj_0, zs_t_d, state_d, n_samples=n_samples)

        p_ratio = ss_util.flatten()/greedy_util.flatten()
        solu = list(mwis)
        q_totals.append(len(solu))
        p_ratios.append(p_ratio[0])
        z_means.append(np.mean(zs_t.numpy()))
        p_corrs.append(apu_avg)
        f_ct += 1
        if cnt < batch_size - 1:
            cnt += 1
            continue
        else:
            cnt = 0
            runtime = time.time() - newtime
            newtime = time.time()

        test_ratio = []
        test_ratio2 = []
        test_len = len(test_mat_names)
        # It is easier to work with numpy
        grad_distr = [dqn_agent_d.memory_crt[i][0][0].numpy() for i in range(len(dqn_agent_d.critic))]
        grad_central = dqn_agent.memory_crt[0][0][0].numpy()
        difference = grad_avg_experiment(grad_distr, grad_central, t=500, verbose=False)
        plt.plot(*list(zip(*difference)), '-o', markersize=3)
        plt.grid()
        plt.xlabel('t')
        plt.ylabel('||Central - Distributed||_F')
        plt.savefig('diff_result')
        import pdb; pdb.set_trace()
        for j in range(test_len):
            mat_contents = sio.loadmat(test_datapath + '/' + test_mat_names[j % test_len])
            adj_0 = mat_contents['adj']
            wts = mat_contents['weights'].transpose()
            nn = adj_0.shape[0]
            _, greedy_util = greedy_search(adj_0, wts)
            bsf_q = []
            q_ct = 0
            res_ct = 0
            out_id = -1
            _, best_IS_util = dqn_agent.solve_mwis(adj_0, wts, train=False)
            test_ratio.append(best_IS_util / greedy_util)

        if np.mean(test_ratio) > best_ratio:
            dqn_agent.save(os.path.join(model_origin, 'cp-{epoch:04d}.ckpt'.format(epoch=epoch)))
            dqn_agent.save_critic(os.path.join(critic_origin, 'cp-{epoch:04d}.ckpt'.format(epoch=epoch)))
            best_ratio = np.mean(test_ratio)
        loss = dqn_agent.replay(batch_size)
        loss_crt = dqn_agent.replay_crt(batch_size)
        loss_d = dqn_agent_d.replay(batch_size)
        loss_crt_d = dqn_agent_d.replay_crt(batch_size)
        if loss is None:
            loss = float('NaN')
        losses.append(loss)

        tr_factor = -np.nanmean(test_ratio)/loss
        if tr_factor > tr_best:
            tr_best = tr_factor
        tr_dive = (tr_factor - tr_best)/tr_best

        print("Epoch: {}".format(epoch),
              "ID: %03d" % f_ct,
              "Model: Actor",
              "Train_Ratio: {:.4f}".format(np.mean(p_ratios)),
              "Test_Ratio: {:.4f}".format(np.mean(test_ratio)),
              "Loss: {:.4f}".format(loss),
              "Corr: {:.4f}".format(np.mean(p_corrs)),
              "L_Avg: {:.4f}".format(np.mean(loss_crt)),
              "Track: {:.4f}".format(tr_factor),
              "runtime: {:.2f}".format(runtime),
              "z_avg: {:.3f}".format(np.nanmean(z_means)))
        p_ratios = []
        z_means = []
        p_corrs = []

    loss_vec.append(np.mean(losses))
print(loss_vec)

