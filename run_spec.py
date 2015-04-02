#!/usr/bin/python
# Author: Jeongseob Ahn (ahnjeong@umich.edu)

import sys, os, time, shlex, signal, getopt
import atexit, socket, getpass
import paramiko # apt-get install python-paramiko
from subprocess import *
from time import localtime, strftime
from threading import Thread, Lock

SPEC_ROOT_DIR = '/home/jeongseob/SPECCPU_2006'
SPEC_RUN_PATH = SPEC_ROOT_DIR + "/run_spec.sh" 

def usage():
	print 'Usage: %s -i workloads.cfg -s hostname -u username' % sys.argv[0]

#
# Each thread runs a benchmark
# Note: if there is a thread which does not complete its job, the other threads run their benchmark again 
#
class run_spec(Thread):
	def __init__(self, ThreadID, BenchID):
		super(run_spec, self).__init__()
		self.threadID = ThreadID
		self.benchmark = BenchID
		self.iteration = 0
	
		self.ssh = paramiko.SSHClient()
		self.ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
		self.ssh.connect(target_host, username=user, password=passwd)
		self.transport = self.ssh.get_transport()

	def run(self):

		while not all (is_completed) :
			cmd = 'cd ' + SPEC_ROOT_DIR
			cmd = cmd + '; source shrc'
			cmd = cmd + '; ' + spec_run_cmd + ' ' + self.benchmark + ' > ' + spec_output_path + '/' + self.benchmark + '.' + benchname + '.specout.' + str(self.iteration)

			date = strftime("%H:%M:%S", localtime())

			if verbose :
				print '[Tid: ' + str(self.threadID) + '] ' + cmd
			else :
				print '[Tid: ' + str(self.threadID) + '] ' + self.benchmark + '(' + str(self.iteration) + ') - ' + date
	
			session = self.transport.open_session()
			session.get_pty()
			session.exec_command(cmd)
			stdout = session.makefile('rb', -1)
			stdout.channel.recv_exit_status()
			is_completed[self.threadID] = True 
			session.close()
			self.iteration += 1


#
# Main function
#

def main(argv=None):

	global spec_output_path, spec_run_cmd
	global benchname
	global is_completed
	global target_host, user, passwd
	global verbose

	try:
		opts, args = getopt.getopt(sys.argv[1:], 'h:i:t:u:c:v', ['help', 'input='])
	except getopt.GetoptError as err:
		print (err)
		sys.exit(1)

	target_host = 'ahn-vm01'
	user = 'jeongseob'
	input = 'workloads'
	verbose = False
	spec_cfg = 'spec.cfg'
	spec_run_cmd = 'runspec --action=run --tune=base --noreportable'

	for o, a in opts:
		if o == '-v':
			verbose = True
		elif o in ('-h', '--help'):
			usage()
			sys.exit()
		elif o in ('-i', '--input'):
			input = a;
		elif o in ('-t', '--target'):
			target_host = a;
		elif o in ('-u', '--user'):
			user = a;
		elif o in ('-c', '--cfg'):
			spec_cfg = a;	
		else:
			assert False, 'unhandled options'

	if not os.path.isfile(input):
		print 'Error: cannot find workload list file(' + workloads_file + ') file.'
		sys.exit(1)

	if not os.path.isfile(spec_cfg):
		print 'Error: cannot find spec2006 configuration file(' + spec_cfg + ') file.'
		sys.exit(1)
	else:
		with open(spec_cfg) as fp:
			for line in fp:
				if line[0][0] == '#':
					continue
				line = line.strip('\n')
				spec_run_cmd = spec_run_cmd + ' ' + line
				

	# SSH
	ssh = paramiko.SSHClient()
	ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())

	try:
		passwd = getpass.getpass(prompt='ssh ' + user + '@' + target_host + '\nPassword: ')
		ssh.connect(target_host, username=user, password=passwd)
		transport = ssh.get_transport()
	except socket.error:
		print 'Error: could not SSH to %s. Please check your server.' % target_host
		sys.exit(1)
	except paramiko.ssh_exception.AuthenticationException :
		print 'Error: authentication failed. Please check your password.'
		sys.exit(1)

	# Setup output directories for SPEC
	start_time = time.time()
	date = strftime("%m%d%Y-%H%M", localtime())
	output_path = "results/%s" % date
	if not os.path.isdir(output_path):
		os.makedirs(output_path)

	spec_output_path = SPEC_ROOT_DIR + "/results/%s" % (date)	
	session = transport.open_session()
	session.get_pty()
	session.exec_command('mkdir -p ' + spec_output_path)
	session.close()

	# Turn off ASLR
	if verbose :
		print 'Turning off ASLR'
	session = transport.open_session()
	session.get_pty()
	session.exec_command('echo 0 | sudo tee -a /proc/sys/kernel/randomize_va_space')
	stdin = session.makefile('wb', -1)
	stdin.write(passwd + '\n')
	stdin.flush()
	session.close()

	with open(input) as fp:
		for line in fp:
			if line[0][0] == '#':
				continue
			line = line.strip('\n')
			line = line.replace(' ', '')
			benchmark_list = line.split(',')

			is_completed= []
			for i in range(0, len (benchmark_list) ) :
				is_completed.append(False)
	
			if verbose :
				print 'Freeing pagecache'
			session = transport.open_session()
			session.get_pty()
			session.exec_command('echo 3 | sudo tee -a /proc/sys/vm/drop_caches')
			stdin = session.makefile('wb', -1)
			stdin.write(passwd + '\n')
			stdin.flush()
			session.close()
	
			benchname = '-'.join(str(e) for e in benchmark_list)
			print "Run %s " % benchname
		
			# Create threads for each benchmark	
			threads = []
			for i, benchmark in list(enumerate(benchmark_list)): 
				th = run_spec(i, benchmark)
				threads.append(th)
				th.start()
		
			for th in threads:
				th.join()
	
			if verbose:
				print "Waiting... to warm the states"
			time.sleep(10)	
		
		# Copy output files
		# FIX ME: it does not support recursive directories
		if verbose:
			print 'copying the output files into the %s' % output_path
		transport = paramiko.Transport((target_host, 22))	
		transport.connect(username = user, password = passwd)
		sftp = paramiko.SFTPClient.from_transport(transport)
		file_list = sftp.listdir(spec_output_path)
		for file in file_list:
			remote_file = spec_output_path + '/' + file   
			local_file = os.getcwd() + '/' + output_path + '/' + file
			sftp.get(remote_file, local_file)
	
		sftp.close()
		transport.close()

	print "Done"

	end_time = time.time()

	print "Time elapsed: ", end_time-start_time
	print "Output path: ", output_path
	
if __name__ == '__main__' :
	sys.exit(main())	
