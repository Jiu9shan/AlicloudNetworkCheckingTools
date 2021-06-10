# -*- coding: UTF-8 -*-
#!/usr/bin/env python

import commands
import sys
import os
import time
import argparse
import logging


origin_sys = {
    'default_route': 1,
    'rp_filter': 0,
    'tw_recycle': 0,
    'nf_conntrack': 0,
    'tw_overflow': 0,
    'time_wait': 0,
    'tw_reuse': 0,
    'timestamp': 0,
    'bootproto': 'static',
    'udpmem_max': 0,
    'mtu_frag': 0,
    'backlog': 0,
    'syn_queue': 0
}


def init_log():
    '''
    初始化logging模块
    '''
    # 创建一个logger;
    logger = logging.getLogger()
    logger.setLevel(logging.DEBUG)
    # 创建一个handler,用于写入日志文件;
    fh = logging.FileHandler('/tmp/ecscheck.log')
    fh.setLevel(logging.INFO)
    # 定义handler的输出格式
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    fh.setFormatter(formatter)
    # 给logger添加handler
    logger.addHandler(fh)


def check_output(cmd):
    ret = commands.getoutput(cmd)
    return ret.split('\n')


class CheckVm(object):
    '''检查vm内部参数相关配置'''
    def __init__(self):
        self.Verbose = False
        self.KernelVersion = 3

    def check_default_route(self):
        '''检查ecs是否存在默认路由'''
        cmd = 'ip route show match 0.0.0.0/0 | wc -l'
        number = check_output(cmd)
        return number[0]

    def check_rp_filter(self):
        '''检查rp_filter是否关闭'''
        cmd = "sysctl -a 2>/dev/null|grep '\.rp_filter'|awk -F'=' '{print $2}'| uniq"
        number = check_output(cmd)
        return int(number[0])

    def check_tw_recycle(self):
        '''检查ecs是否开启了tw_recycle参数'''
        cmd = "sysctl -a 2>/dev/null|grep tw_recycle | awk -F '=' '{print $2}'"
        number = check_output(cmd)
        return int(number[0])

    def check_nf_conntrack(self):
        '''检查连接跟踪表是否溢出'''
        cmd = "dmesg|grep nf_conntrack|grep 'table full, dropping packet'|wc -l"
        number = check_output(cmd)
        return number[0]

    def check_time_wait(self):
        '''检查是否有time_wait连接数超过最大值，导致无法建立连接'''
        # cmd1 = 'netstat -ant | grep TIME_WAIT | wc -l'
        cmd1 = "ss -s | grep timewait | awk -F 'timewait' '{print $2}' | awk -F'/' '{print $1}'"
        cmd2 = "sysctl -a 2>/dev/null|grep tcp_max_tw_buckets | awk -F'=' '{print $2}'"
        real_num = int(check_output(cmd1)[0])
        sys_num = int(check_output(cmd2)[0])
        if real_num > sys_num:
            return 1
        else:
            return 0

    def check_tw_reuse(self):
        '''检查tw_reuse参数是否打开'''
        cmd = "sysctl -a 2>/dev/null| grep tcp_tw_reuse | awk -F '=' '{print $2}'"
        number = check_output(cmd)
        return int(number[0])

    def check_timestamp(self):
        '''检查是否因为tw_recycle, timestamp同时开启导致丢包'''
        cmd = "netstat -s |grep 'because of timestamp' | wc -l"
        cmd2 = "netstat -s |grep 'because of timestamp' | awk '{print $1}'"
        number = check_output(cmd)
        if int(number[0]) == 1:
            fir_number = int(check_output(cmd2)[0])
            if self.Verbose:
                logging.info('The packets drooped by timestamp is: %s' % fir_number)
            time.sleep(5)
            sec_number = int(check_output(cmd2)[0])
            if sec_number - fir_number > 0:
                return 1
            elif sec_number == fir_number:
                return 2
        else:
            return number[0]

    def check_udpmem_max(self):
        '''
        检查是否存在由于udp窗口过小导致的协议栈丢包
        返回码1代表有丢包，且在增长
        返回码2代表有丢包，但未增长
        返回码0代表无丢包
        '''
        cmd = "cat /proc/net/snmp | grep 'Udp:' | awk '{print $4}'|sed -n '2p'"
        fir_stats = int(check_output(cmd)[0])
        if self.Verbose:
            logging.info('The packets dropped by udpmem is: %s' % fir_stats)
        time.sleep(5)
        sec_stats = int(check_output(cmd)[0])
        if sec_stats - fir_stats > 0:
            return 1
        elif fir_stats > 0:
            return 2
        else:
            return 0

    def check_mtu(self):
        '''
        检查是否存在由于mtu过小导致的协议栈丢包
        返回码1代表有丢包，且在增长
        返回码2代表有丢包，但未增长
        返回码0代表无丢包
        '''
        cmd = "cat /proc/net/snmp|grep FragFails -C 1|awk '{print $(NF-1)}'|sed -n 2p"
        fir_stats = int(check_output(cmd)[0])
        if self.Verbose:
            logging.info('The packets dropped by mtu is: %s' % fir_stats)
        time.sleep(5)
        sec_stats = int(check_output(cmd)[0])
        if sec_stats - fir_stats > 0:
            return 1
        elif fir_stats > 0:
            return 2
        else:
            return 0

    def check_iptables(self):
        '''列出iptables丢包计数'''
        cmd = 'iptables -L -n -v | grep -i drop'
        ret = check_output(cmd)
        if self.Verbose:
            logging.info(ret)
        return ret

    def check_backlog(self):
        '''检查是否有由于tcp接收队列溢出导致的丢包'''
        number = 0
        cmd = "netstat -s | grep 'listen queue of a socket overflowed'"
        line = check_output(cmd)
        if len(line[0]) > 1:
            number = int(line[0].split(' ')[4])
        return number

    def check_syn_queue(self):
        '''检查是否有因为tcp syn队列满导致的丢包'''
        number = 0
        cmd = "netstat -s | grep 'SYNs to LISTEN sockets dropped'"
        line = check_output(cmd)
        if len(line[0]) > 1:
            number = int(line[0].split(' ')[4])
        return number

    def check(self, KernelVersion, Verbose=False):
        if Verbose:
            self.Verbose = True
        host_info = dict()
        host_info['default_route'] = self.check_default_route()
        host_info['rp_filter'] = self.check_rp_filter()
        if KernelVersion < 4:
            host_info['tw_recycle'] = self.check_tw_recycle()
        host_info['nf_conntrack'] = self.check_nf_conntrack()
        host_info['time_wait'] = self.check_time_wait()
        host_info['tw_reuse'] = self.check_tw_reuse()
        host_info['timestamp'] = self.check_timestamp()
        host_info['udpmem_max'] = self.check_udpmem_max()
        host_info['mtu_frag'] = self.check_mtu()
        host_info['backlog'] = self.check_backlog()
        host_info['syn_queue'] = self.check_syn_queue()
        host_info['iptables'] = self.check_iptables()
        return host_info


class CheckCentos(object):
    '''检查vm内部参数相关配置'''
    def __init__(self):
        self.Verbose = False

    def check_tw_overflow(self):
        '''检查是否产生tw overflow'''
        cmd = "grep 'time wait bucket table overflow' /var/log/messages |wc -l"
        number = check_output(cmd)
        return number[0]

    def check_bootproto(self):
        '''检查ip分配方式是否为static'''
        cmd = "grep -i bootproto /etc/sysconfig/network-scripts/ifcfg-eth0|awk -F'=' '{print $NF}'"
        result = check_output(cmd)
        return result[0]

    def check(self):
        host_info = dict()
        host_info['tw_overflow'] = self.check_tw_overflow()
        host_info['bootproto'] = self.check_bootproto()
        return host_info


class CheckUbuntu(object):
    '''检查vm内部参数相关配置'''
    def __init__(self):
        pass

    def check_tw_overflow(self):
        '''检查是否产生tw overflow'''
        cmd = "grep 'time wait bucket table overflow' /var/log/syslog|wc -l"
        number = check_output(cmd)
        return number[0]

    def check_bootproto(self):
        '''检查ip分配方式是否为static'''
        cmd = "grep eth0 /etc/network/interfaces|grep inet|awk '{print $NF}'"
        result = check_output(cmd)
        return result[0]

    def check(self):
        host_info = dict()
        host_info['tw_overflow'] = self.check_tw_overflow()
        host_info['bootproto'] = self.check_bootproto()
        return host_info


class CheckSUSE(object):
    '''检查vm内部参数相关配置'''
    def __init__(self):
        pass

    def check_tw_overflow(self):
        '''检查是否产生tw overflow'''
        cmd = "grep 'time wait bucket table overflow' /var/log/messages |wc -l"
        number = check_output(cmd)
        return number[0]

    def check_bootproto(self):
        '''检查ip分配方式是否为static'''
        cmd = "grep -i bootproto /etc/sysconfig/network/ifcfg-eth0|awk -F'=' '{print $NF}'"
        result = check_output(cmd)
        return result[0]

    def check(self):
        host_info = dict()
        host_info['tw_overflow'] = self.check_tw_overflow()
        host_info['bootproto'] = self.check_bootproto()
        return host_info


Command_handlers = {
    'Aliyun': CheckCentos(),
    'CentOS': CheckCentos(),
    'Ubuntu': CheckUbuntu(),
    'SUSE LINUX': CheckSUSE()
}


def judge_version():
    '''判断linux系统的发型版本'''
    cmd = "lsb_release -a | grep Distributor | awk -F':' '{print $2}'"
    version = check_output(cmd)[0].strip()
    if version in Command_handlers.keys():
        return Command_handlers[version]
    else:
        return Command_handlers['CentOS']


def check_kernel():
    '''判断内核版本'''
    cmd = "uname -r | awk -F '.' '{print $1}'"
    version = int(os.popen(cmd).read().split('\n')[0])
    return version


def compare(item, v1, v2, Verbose=False):
    '''比较v1，v2'''
    if str(v1) != str(v2) and not Verbose:
        print myAlign(item, 20) + ':' + ' error' + '(standard_value: %s, vm_value: %s)' % (v1, v2)
        return 1
    elif str(v1) != str(v2) and Verbose:
        return 1
    elif str(v1) == str(v2) and not Verbose:
        print myAlign(item, 20) + ':' + ' ok'
        return 0
    else:
        return 0


def myAlign(string, length=0):
    '''
    格式化输出
    '''
    if length == 0:
        return string
    slen = len(string)
    re = string
    if isinstance(string, str):
        placeholder = ' '
    else:
        placeholder = u'　'

    while slen < length:
        re += placeholder
        slen += 1
    return re


def get_options(x):
    parser = argparse.ArgumentParser("\tNOTE:\nThis tool can check the packets dropped by kernel\n")
    parser.add_argument("-v", "--verbosity", action="count",
                        help="increase output verbosity")
    parser.add_argument("-D", "--daemon", action="store_true",
                        help="Run in the background and log the data")
    parser.add_argument("-i", "--interval",
                        help="Specify the interval of the script")
    opt = parser.parse_args(args=x)
    if opt.verbosity > 2:
        sys.stderr.write("%s\n" % opt)
    return opt


def Run_check(Verbose=False, interval=1):
    '''Verbose为True时，循环执行, 默认间隔为1s'''
    while True:
        kernel_version = check_kernel()
        print kernel_version
        host_info = CheckVm().check(kernel_version, Verbose).copy()
        vm_extra = judge_version().check()
        host_info.update(vm_extra)
        compare('default_route', origin_sys['default_route'],
                host_info['default_route'], Verbose)
        compare('rp_filter', origin_sys['rp_filter'],
                host_info['rp_filter'], Verbose)
        if kernel_version < 4:
            compare('tw_recycle', origin_sys['tw_recycle'],
                    host_info['tw_recycle'], Verbose)
        compare('nf_conntrack', origin_sys['nf_conntrack'],
                host_info['nf_conntrack'], Verbose)
        compare('tw_overflow', origin_sys['tw_overflow'],
                host_info['tw_overflow'], Verbose)
        compare('time_wait', origin_sys['time_wait'],
                host_info['time_wait'], Verbose)
        compare('tw_reuse', origin_sys['tw_reuse'],
                host_info['tw_reuse'], Verbose)
        compare('timestamp', origin_sys['timestamp'],
                host_info['timestamp'], Verbose)
        compare('bootproto', origin_sys['bootproto'],
                host_info['bootproto'], Verbose)
        compare('udpmem_max', origin_sys['udpmem_max'],
                host_info['udpmem_max'], Verbose)
        compare('mtu_frag', origin_sys['mtu_frag'],
                host_info['mtu_frag'], Verbose)
        compare('backlog', origin_sys['backlog'],
                host_info['backlog'], Verbose)
        compare('syn_queue', origin_sys['syn_queue'],
                host_info['syn_queue'], Verbose)
        print '*' * 41 + ' Iptables Check Result ' + '*' * 41
        print ('   pkts bytes target     prot opt in     out     source'
               '      destination')
        for line in host_info['iptables']:
            print line
        if Verbose:
            time.sleep(interval)
        else:
            break


def main():
    '''1) 后台运行不输出到控制台，仅打日志;
       2) 前台运行直接输出结果;'''
    opt = get_options(sys.argv[1:])
    if opt.daemon:
        Verbose = True
    else:
        Verbose = False
    if opt.interval:
        interval = float(opt.interval)
    if not Verbose:
        print '\033[1;32;40m'
        print '*' * 41 + ' Vm Check Result ' + '*' * 41
        Run_check(Verbose)
        print '\033[1;31;40m'
        print '*' * 41 + ' 字段含义解释 ' + '*' * 41
        print Tips
        print '*' * 100
        print '\033[0m'
    else:
        Run_check(Verbose, interval)


Tips = """
default_route  :  默认路由条目数，正常情况下，每台ecs都有一条默认路由;
rp_filter      :  反向过滤，验证数据包出口和入口是否是同一块网卡, 建议关闭;
tw_recycle     :  time_wait 状态连接快速回收，7U系统中，会对timestamp做递增性验证，容易导致丢包,net.ipv4.tcp_tw_recycle=0;
nf_conntrack   :  连接跟踪表，检查是否存在连接跟踪表溢出都情况，为1代表有溢出;
tw_overflow    :  time_wait 状态bucket溢出,tw状态连接得不到快速回收，为1代表有溢出;
time_wait      :  检查是否有time_wait连接数超过最大值，导致无法建立连接,为1代表有超过;
tw_reuse       :  time_wait 状态连接数复用，可以改善tw溢出的情况，但在使用slb的情况下，一定概率会触发复用老的session信息，导致转发异常,视情况开启,为1代表开启;
timestamp      :  检查是否存在因为timestamp, tw_recycle同时开启，导致tcp连接无法建立，而产生丢包的计数，0无丢包，1有丢包记录且增长，2有丢包但无增长;
bootproto      :  检查vm内部ip分配策略，默认是static, 部分镜像支持dhcp;
udpmem_max     :  检查是否存在由于udp窗口过小导致的协议栈丢包, 0无丢包，1有丢包且在增长，2有丢包但无增长;
mtu_frag       :  检查是否存在由于mtu导致的分片失败;
backlog        :  检查是否存在由于tcp接收队列满导致的丢包;
syn_queue      :  检查是否存在由于syn队列满导致的丢包;

# 脚本适配的版本: Aliyun, CentOS, Ubuntu, SUSE LINUX, 若无lsb_release 按照
# Centos 处理。
"""

if __name__ == "__main__":
    init_log()
    main()

