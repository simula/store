"""
   The MIT License (MIT)

   Copyright (c) 2017

   Permission is hereby granted, free of charge, to any person obtaining a copy
   of this software and associated documentation files (the "Software"), to deal
   in the Software without restriction, including without limitation the rights
   to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
   copies of the Software, and to permit persons to whom the Software is
   furnished to do so, subject to the following conditions:
   
   The above copyright notice and this permission notice shall be included in all
   copies or substantial portions of the Software.
   
   THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
   IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
   FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
   AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
   LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
   OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
   SOFTWARE.
"""

"""
    File name: sma_app.py
    Author: Lukasz Kulacz and navid nikaein
    Description: This app dynamically updates the RRM policy based on the statistics received through FLEXRAN SDK
    version: 1.0
    Date created: 7 July 2017
    Date last modified: 7 July 2017 
    Python Version: 2.7
    
"""
from operator import itemgetter, attrgetter, methodcaller
from random import shuffle
import random
from lib import flexran_sdk 
from lib import logger
from threading import Timer
from time import sleep
import argparse
import json
import yaml
import tornado 
import datetime

from lib import polish_calc as calc

from lib import app_sdk

class sma_app(object):

    general_policy = []
    operator_policy = []
    lsa_policy = []
    rules = []
    sensing_data = []
    options = []
    base_stations = []
    decisions = []
    next_decisions = []
    changes = []
    output = []

    period=1
    name="sma_app"
    
    def __init__(self, log, url='http://localhost',port='9999',log_level='info', op_mode='test'):
        super(sma_app, self).__init__()
        
        self.url = url+port
        self.log_level = log_level
        self.status = 0
        self.op_mode = op_mode
        self.app_handler=None
    

    def register(self, client, message):
        # add to the list and check if already exsit
        self.app_handler = client
        print message
    def unregister(self, client, message):
        # remove to the list and check if already exsit
        self.app_handler = None
        print message 

    def load_rrm_data(self):
        log.info('Current number of eNB attached to rtc: ' + str(sm.get_num_enb()))
        self.base_stations = [];
        for enb in range(sm.get_num_enb()):          
            dlFreq = sm.get_cell_freq(enb,dir='dl')
            dlBand = sm.get_cell_bw(enb,dir='dl')
            ulFreq = sm.get_cell_freq(enb,dir='ul')
            ulBand = sm.get_cell_bw(enb,dir='ul')
            self.base_stations.append({'dl_freq':dlFreq, \
                                       'ul_freq':ulFreq, \
                                       'dl_bandwidth': dlBand, 'ul_bandwidth': ulBand})
        log.debug('All eNB attached to rtc, that we can control: ')
        log.info(yaml.dump(self.base_stations))

    def add_operator_options(self):
         for op in range(len(self.operator_policy)):
            for f_index in range(len(self.operator_policy[op]['freq_min'])):
                f_min_policy = self.operator_policy[op]['freq_min'][f_index]
                f_max_policy = self.operator_policy[op]['freq_max'][f_index]
                busy = False
                for bs in range(len(self.sensing_data)):
                    f_min_bs = self.sensing_data[bs]['freq_min']
                    f_max_bs = self.sensing_data[bs]['freq_max']
    
                    if self.sensing_data[bs]['operator'] == self.operator_policy[op]['operator'] and \
                       f_max_bs > f_min_policy and f_min_bs < f_max_policy:
                       busy = True
                       break  #  detect at least one to apply the rigt policy
                if busy:
                  self.options.append({'lsa':False,'operator':self.operator_policy[op]['operator'],\
                              'freq_min': self.operator_policy[op]['busy']['sub_freq_min'][f_index], \
                              'freq_max': self.operator_policy[op]['busy']['sub_freq_max'][f_index], \
                              'bandwidth': self.operator_policy[op]['busy']['sub_freq_max'][f_index] - \
                                        self.operator_policy[op]['busy']['sub_freq_min'][f_index],\
                              'min_lease_time': self.operator_policy[op]['busy']['min_lease_time'][f_index], \
                              'duration_lease': self.operator_policy[op]['busy']['min_lease_time'][f_index] * \
                                                self.operator_policy[op]['busy']['max_lease_count'][f_index], \
                              'price': 1.0*self.operator_policy[op]['busy']['price'][f_index]/\
                                         self.operator_policy[op]['busy']['min_lease_time'][f_index]  })
                else:
                  self.options.append({'lsa':False,'operator':self.operator_policy[op]['operator'],\
                              'freq_min': f_min_policy, 'freq_max': f_max_policy, \
                              'bandwidth': f_max_policy - f_min_policy, \
                              'min_lease_time': self.operator_policy[op]['idle']['min_lease_time'][f_index], \
                              'duration_lease': self.operator_policy[op]['idle']['min_lease_time'][f_index] * \
                                                self.operator_policy[op]['idle']['max_lease_count'][f_index], \
                              'price': 1.0*self.operator_policy[op]['idle']['price'][f_index]/\
                                        self.operator_policy[op]['idle']['min_lease_time'][f_index]})

    def add_lsa_options(self):
       for i in range(len(self.lsa_policy)):
           for f_index in range(len(self.lsa_policy[i]['freq_min'])):
              f_min = self.lsa_policy[i]['freq_min'][f_index]
              f_max = self.lsa_policy[i]['freq_max'][f_index]
              bandwidth = f_max - f_min
              price = self.lsa_policy[i]['price'][f_index]
              time = self.lsa_policy[i]['min_lease_time'][f_index]
              count = self.lsa_policy[i]['max_lease_count'][f_index]
              self.options.append({'lsa':True,'freq_min': f_min, 'freq_max': f_max, 'duration_lease': time * count, \
                                 'bandwidth': bandwidth,'min_lease_time': time, 'price': 1.0*price/time})
       log.debug('All available options: ')
       log.debug(yaml.dump(self.options))

    def filter_options(self,rule):

        for criteria in self.rules[rule]['criteria'].keys():
            if self.rules[rule]['criteria'][criteria][0] == 0:
               continue
            log.info('Apply criteria: ' + criteria + ' ' + self.rules[rule]['criteria'][criteria][1] \
                        + ' than ' + str(self.rules[rule]['criteria'][criteria][0]))
            if self.rules[rule]['criteria'][criteria][1] == 'more':
               for option in self.options[:]:
                  if option[criteria] < self.rules[rule]['criteria'][criteria][0]:
                     self.options.remove(option)
            else:
               for option in self.options[:]:
                  if option[criteria] > self.rules[rule]['criteria'][criteria][0]:
                     self.options.remove(option)

    def calculate_weights(self,rule):
        max_values = self.options[0].copy()
        max_values['freq_min'] = max(self.options,key=lambda k:k['freq_min'])['freq_min']
        max_values['freq_max'] = max(self.options,key=lambda k:k['freq_max'])['freq_max']
        max_values['duration_lease'] = max(self.options,key=lambda k:k['duration_lease'])['duration_lease']
        max_values['bandwidth'] = max(self.options,key=lambda k:k['bandwidth'])['bandwidth']
        max_values['min_lease_time'] = max(self.options,key=lambda k:k['min_lease_time'])['min_lease_time']
        max_values['price'] = max(self.options,key=lambda k:k['price'])['price']
        weight_sum = sum(self.rules[rule]['cost'].values())
        operator_weight_max = max(self.rules[rule]['operator_preference'].values())
        for option in range(len(self.options)):
            weight = 0
            if self.rules[rule]['use_pattern']:
                pattern = self.rules[rule]['pattern'].split(' ')
                #print pattern
                for i in range(len(pattern)):
                    for opt_par in self.options[option]:
                        if pattern[i] == opt_par:
                            pattern[i] = self.options[option][opt_par]
                #print pattern
                try:
                    pattern_rpn = calc.infixToRPN(pattern)
                    weight = calc.parse_rpn(pattern_rpn)
    
                    #print weight
                except:
                    log.error('Error in cost pattern (wrong pattern or wrong param name) weight = 0')

            else:
                for param in range(len(self.rules[rule]['cost'])):
                    param_name = self.rules[rule]['cost'].keys()[param]
                    if(param_name == 'price'):
                         weight += self.rules[rule]['cost'][param_name] * \
                             (1.0 - 1.0*self.options[option][param_name]/max_values[param_name])
                    elif(param_name == 'freq_higher'):
                         weight += self.rules[rule]['cost'][param_name] * \
                             (1.0*self.options[option]['freq_max']/max_values['freq_max'])
                    elif(param_name == 'freq_lower'):
                         (1.0 - 1.0*self.options[option]['freq_min']/max_values['freq_min'])
                    elif(param_name in self.options[option]):
                        weight += self.rules[rule]['cost'][param_name] * \
                         (1.0*self.options[option][param_name]/max_values[param_name])
                    else:
                        log.warn('Wrong COST name, skipped cost: ' + param_name)
                
                if weight_sum == 0:
                    weight = random.random();
                else:
                    weight /= weight_sum
             
            # apply operators preference (operator or lsa)
            if self.options[option]['lsa'] == True:
                weight *= 1.0*self.rules[rule]['operator_preference']['lsa']/operator_weight_max
            else:                
                for operator in self.rules[rule]['operator_preference'].keys():
                   if self.options[option]['operator'] == operator:
                      weight *= 1.0*self.rules[rule]['operator_preference'][operator]/operator_weight_max
                      break
            # apply frequency preference 
            for freq_pref in self.rules[rule]['freq_preference']:
                 fmin_pref = freq_pref['freq_min']
                 fmax_pref = freq_pref['freq_max']
                 multiplier = freq_pref['multiplier']
                 fmin_option = self.options[option]['freq_min']
                 fmax_option = self.options[option]['freq_max']  
                 if(fmin_pref >= fmin_option and fmax_pref <= fmax_option):
                     percentage = 1.0        
                 elif(fmax_pref >= fmin_option and fmax_pref <= fmax_option):
                     percentage = 1.0*(fmax_pref - fmin_option)/(fmax_pref - fmin_pref) 
                 elif(fmin_pref >= fmin_option and fmin_pref <= fmax_option):
                     percentage = 1.0*(fmax_option - fmin_pref)/(fmax_pref - fmin_pref)
                 else: 
                     percentage = 0.0;
                 weight *= (1 + percentage * multiplier)
            self.options[option]['weight']= weight
        
    def filter_with_general_rules(self):
        for opt in self.options:
            for i in range(len(self.general_policy)):
                fmin_opt = opt['freq_min']
                fmax_opt = opt['freq_max']
                fmin_gen = self.general_policy[i]['freq_min']
                fmax_gen = self.general_policy[i]['freq_max']  
                if fmax_gen > fmin_opt and fmin_gen < fmax_opt:
                    opt['frame_type'] = self.general_policy[i]['frame_type'].upper()
                    if opt['frame_type'] == 'FDD':
                        opt['fdd_spacing'] = self.general_policy[i]['fdd_spacing']
                    else:
                        opt['fdd_spacing'] = 0
                    break


    def make_decision(self):
        self.next_decisions = []
        for bs in range(sm.get_num_enb()):
           for rule_index in range(len(self.rules)):
                self.options = []
                self.add_operator_options()
                self.add_lsa_options()
                self.filter_with_general_rules()

                # filter and calculate options
                self.filter_options(rule_index)
                self.calculate_weights(rule_index)           
                   
                # choose the best one
                self.options = sorted(self.options, key=lambda k: k['weight'],reverse = True)

                log.debug('\n' + yaml.dump(self.options))
       
                # save option to next_decision vector
                if len(self.options) > 0:
                    self.options[0]['eNB_index'] = bs
                    self.options[0]['MVNO_name'] = self.rules[rule_index]['MVNO_name']
                    self.next_decisions.append(self.options[0]) 
                else:
                    self.next_decisions.append({'error':'No options available'})

        log.debug('Next decisions: ')
        log.debug(yaml.dump(self.next_decisions))

    def check_changes_policy(self):
        if(len(self.decisions) == 0):
            # first time 
           self.decisions = self.next_decisions 
           self.changes = self.decisions
           log.info('Set first time policy')
           log.debug(self.decisions)
           return # to assign for first time use

        a = []
        for i in range(len(self.decisions)):
            a.append({})  
            if(self.decisions[i] == self.next_decisions[i]): # if the current decision is the same as previous, skip 
                log.info('Skip changes to eNB: ' + str(self.decisions[i]['eNB_index']) + \
                         ' MVNO_name: ' + str(self.decisions[i]['MVNO_name']))
                self.decisions[i] = self.next_decisions[i]
            else:
                log.info('Change policy to eNB: ' + str(self.next_decisions[i]['eNB_index']) + \
                        ' MVNO_name: ' + str(self.next_decisions[i]['MVNO_name'])) 
                for j in self.decisions[i].keys():
                    if (self.decisions[i][j] != self.next_decisions[i][j]):
                        a[i][j] = self.next_decisions[i][j]
                self.decisions[i] = self.next_decisions[i]

        del self.changes
        self.changes = a


    def translate_bandwidth(self, value):
        if value >= 20:
            return 100
        elif value >= 10:
            return 50
        elif value >= 5:
            return 25
        elif value >= 1.4:
            return 6
        else:
            return 0

    def check_if_decisions_changed(self):
        return  len(self.output['enb']) > 0

    def parse_frame_type(self,frame_type):
        if frame_type == "FDD":
            return int(0)
        elif frame_type == "TDD":
            return int(1)
        else:
            return int(-1)

    def generate_output(self):
        file = open('outputs/output_policy.yaml','w')
        self.output = {'enb': []};


        for i in range(len(self.changes)):
            if len(self.changes[i]) > 0:
                enb_id = self.decisions[i]['eNB_index']
                self.output['enb'].append({enb_id:{}})
                for j in self.changes[i].keys():
                    if j == 'freq_max':
                        self.output['enb'][enb_id][enb_id]['dl_freq']=int(self.changes[i][j]-self.options[i]['bandwidth']/2.0)
                        self.output['enb'][enb_id][enb_id]['ul_freq_offset']=int(self.options[i]['fdd_spacing'])
                    if j == 'bandwidth':
                        self.output['enb'][enb_id][enb_id]['bandwidth']=self.translate_bandwidth(self.options[i]['bandwidth'])
                    if j == 'frame_type':
                        self.output['enb'][enb_id][enb_id]['frame_type']=self.parse_frame_type(self.options[i]['frame_type'])
                        self.output['enb'][enb_id][enb_id]['ul_freq_offset']=int(self.options[i]['fdd_spacing'])
        
        yaml.dump(self.output,file,default_flow_style=False)
        log.info('\n' + yaml.dump(self.output)) 

    def load_policy(self):
        self.rules = ss.get_rules()
        self.lsa_policy = ss.get_lsa_policy()
        self.operator_policy = ss.get_operator_policy()
        self.general_policy = ss.get_general_policy()
        self.sensing_data = ss.get_sensing_data()

    def run(self, sm,sma_app):

        
        log.info('Reading the status of the underlying eNBs')
        sm.stats_manager('all')
        self.load_rrm_data()

        log.info('Load all policy files from ss_policy')
        ss.load_config_files()  
        self.load_policy()
       
        # large time scale
        log.info('Make decision')
        self.make_decision()  # physical BS: there is no selection or a second level of selection
        
        # generate spectrum policy 
        log.info('Generate decision')
        # apply spectrum sharing policy
        self.check_changes_policy()

        self.generate_output()

        if self.check_if_decisions_changed():
            ss.apply_policy(self.output)

        # short time scale
        # self.make_decision () # virtual BS within the same physical BS
        # if the decision is different
            # set istrubctions to rrm_app # ran shring
            # alternatively, do it manualy through sdk

        log.info('Waiting ' + str(sma_app.period) + ' seconds...')
        t = Timer(sma_app.period,self.run,kwargs=dict(sm=sm,sma_app=sma_app))
        t.start()

    def handle_open_data(self, client, message):

        self.app_handler.send(message)
        client.send({'ssss':'sssssssss'})
        print(message)
        
if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Process some integers.')
    
    parser.add_argument('--url', metavar='[option]', action='store', type=str,
                        required=False, default='http://localhost', 
                        help='set the FlexRAN RTC URL: loalhost (default)')
    parser.add_argument('--port', metavar='[option]', action='store', type=str,
                        required=False, default='9999', 
                        help='set the FlexRAN RTC port: 9999 (default)')
    parser.add_argument('--app-port', metavar='[option]', action='store', type=int,
                        required=False, default=8080, 
                        help='set the App port to open data: 8080 (default)')
    parser.add_argument('--op-mode', metavar='[option]', action='store', type=str,
                        required=False, default='test', 
                        help='Set the app operation mode either with FlexRAN or with the test json files: test, sdk(default)')
    parser.add_argument('--log',  metavar='[level]', action='store', type=str,
                        required=False, default='info', 
                        help='set the log level: debug, info (default), warning, error, critical')
    parser.add_argument('--period',  metavar='[option]', action='store', type=int,
                        required=False, default=1, 
                        help='set the period of the app: 1s (default)')

    parser.add_argument('--version', action='version', version='%(prog)s 1.0')

    args = parser.parse_args()
    
    sma_app.period=args.period

    log=flexran_sdk.logger(log_level=args.log).init_logger()

    sma_app = sma_app(log=log)

    rrm = flexran_sdk.rrm_policy(log=log,
                                 url=args.url,
                                 port=args.port,
                                 op_mode=args.op_mode)

    sm = flexran_sdk.stats_manager(log=log,
                                   url=args.url,
                                   port=args.port,
                                 #  op_mode='test')
                                   op_mode=args.op_mode)

    ss = flexran_sdk.ss_policy(log=log,
                               url=args.url,
                               port=args.port,
                               op_mode=args.op_mode)

    log.info('Waiting ' + str(sma_app.period) + ' seconds...')
    t = Timer(sma_app.period, sma_app.run,kwargs=dict(sm=sm,sma_app=sma_app))
    t.start()

    # open data additions 
    app_open_data=app_sdk.app_builder(app=sma_app.name,
                                      address=args.url,
                                      port=args.app_port)

    app_open_data.add_options("time", "current time:" + str(datetime.datetime.now()),lambda x,y:None,lambda x,y:None)
    app_open_data.add_options("list", sma_app.handle_open_data,sma_app.register,sma_app.unregister)
    app_open_data.run_app()
    
    try:
        tornado.ioloop.IOLoop.current().start()
    except:
        pass
    
   
