#!/usr/bin/env python
# ----------------------------------------------------------------------------
# Copyright 2016 Nervana Systems Inc.
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# ----------------------------------------------------------------------------
import ngraph as ng
from ngraph.frontends.neon import (Sequential, Preprocess, BiRNN, Recurrent, Affine,
                                   Softmax, Tanh, LookupTable)
from ngraph.frontends.neon import UniformInit, RMSProp
from ngraph.frontends.neon import ax, ar, loop_train
from ngraph.frontends.neon import NgraphArgparser, make_bound_computation, make_default_callbacks
from ngraph.frontends.neon import SequentialArrayIterator
import ngraph.transformers as ngt

from ptb import PTB


# parse the command line arguments
parser = NgraphArgparser(__doc__)
parser.add_argument('--layer_type', default='rnn', choices=['rnn', 'birnn'],
                    help='type of recurrent layer to use (rnn or birnn)')
parser.add_argument('--use_lut', action='store_true',
                    help='choose to use lut as first layer')
parser.set_defaults(gen_be=False)
args = parser.parse_args()

# these hyperparameters are from the paper
args.batch_size = 50
time_steps = 150
hidden_size = 500

# download penn treebank
tree_bank_data = PTB(path=args.data_dir)
ptb_data = tree_bank_data.load_data()
train_set = SequentialArrayIterator(ptb_data['train'], batch_size=args.batch_size,
                                    time_steps=time_steps, total_iterations=args.num_iterations)

valid_set = SequentialArrayIterator(ptb_data['valid'], batch_size=args.batch_size,
                                    time_steps=time_steps)

inputs = train_set.make_placeholders()
ax.Y.length = len(tree_bank_data.vocab)


def expand_onehot(x):
    # Assign roles
    x.axes.find_by_short_name('time')[0].add_role(ar.time)
    x.axes.find_by_short_name('time')[0].is_recurrent = True
    return ng.one_hot(x, axis=ax.Y)

# weight initialization
init = UniformInit(low=-0.08, high=0.08)

if args.use_lut:
    layer_0 = LookupTable(50, 100, init, update=True, pad_idx=0)
else:
    layer_0 = Preprocess(functor=lambda x: ng.one_hot(x, axis=ax.Y))

if args.layer_type == "rnn":
    rlayer = Recurrent(hidden_size, init, activation=Tanh())
elif args.layer_type == "birnn":
    rlayer = BiRNN(hidden_size, init, activation=Tanh(), return_sequence=True, sum_out=True)

if args.use_lut:
    layer_0 = LookupTable(50, 100, init, update=False)
else:
    layer_0 = Preprocess(functor=expand_onehot)

# model initialization
seq1 = Sequential([layer_0,
                   rlayer,
                   Affine(init, activation=Softmax(), bias_init=init, axes=(ax.Y,))])

optimizer = RMSProp()
output_prob = seq1.train_outputs(inputs['inp_txt'])
loss = ng.cross_entropy_multi(output_prob, ng.one_hot(inputs['tgt_txt'], axis=ax.Y), usebits=True)
mean_cost = ng.mean(loss, out_axes=[])
updates = optimizer(loss)

train_outputs = dict(batch_cost=mean_cost, updates=updates)
loss_outputs = dict(cross_ent_loss=loss)

# Now bind the computations we are interested in
transformer = ngt.make_transformer()
train_computation = make_bound_computation(transformer, train_outputs, inputs)
loss_computation = make_bound_computation(transformer, loss_outputs, inputs)

cbs = make_default_callbacks(output_file=args.output_file,
                             frequency=args.iter_interval,
                             train_computation=train_computation,
                             total_iterations=args.num_iterations,
                             eval_set=valid_set,
                             loss_computation=loss_computation,
                             use_progress_bar=args.progress_bar)

loop_train(train_set, train_computation, cbs)
