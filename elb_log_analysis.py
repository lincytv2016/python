##########################################################################################
#                             Python script to parse elb logs                            #
#                                     Version 1.0.0                                      #
##########################################################################################


import smtplib
import boto3
import time
import os
import re
import calendar
import argparse
import requests
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
import HTML

working_dir = os.getcwd()+'/'

###########################################################
#  Passing paramerts to the code                          # 
###########################################################


parser = argparse.ArgumentParser(usage= '%(prog)s [options]',description='******ELB_LOG_ANALYSIS******', formatter_class=argparse.RawTextHelpFormatter)
parser.add_argument('--version', action = 'version', version = '%(prog)s 1.0.0')
parser.add_argument('-t','--time', type = float, help = 'Specify time in hours, fetch logs for last specified hours')
parser.add_argument('-o','--output', type = str, help = 'Specify the output file \nname(avoid this option will print the output in cosole)')
parser.add_argument('-e','--email', type = str, help = 'Specify the destination email address to receive the output, Max 50 fileds will be available')
parser.add_argument('-r','--result', type = str, help = 'Specify the type of result latency 4xx 5xx source_5xx source_4xx source_3xx source_2xx invalid all')
parser.add_argument('-c','--custom', type = str, help = 'Specify the custom columns separated by coma (Below are custom fields available)\n\
1 : Timestamp\n\
2 : ELB_Name\n\
3 : Client_IP\n\
4 : Client_Port\n\
5 : Backend_IP\n\
6 : Backend_Port\n\
7 : Request_processing_time\n\
8 : Backend_processing_time\n\
9 : Response_processing_time\n\
10 : ELB_status_code\n\
11 : Backend_status_code\n\
12 : Received_Bytes\n\
13 : Sent Bytes\n\
14 : Request\n\
15 : User_Agent\n\
16 : SSL_cipher\n\
17 : SSL_protocol\n\
18 : Country_Code\n\
19 : Organization')
parser.add_argument('-g','--group_by', type = str, help = 'Used to group by specific fields, used along with custom option (Invalid if custom option is not specified).\nAdd an extra count and by default the output will be sorted according to count field(In the absense of sort_by option).')
parser.add_argument('-s','--sort_by', type = str, help = 'Used to sort by a specific field, used along with custom option (Invalid if custom option is not specified).')

args = parser.parse_args()

msg = MIMEMultipart('alternative')
if args.result:
	msg['Subject'] = 'Elb log report ' + args.result
elif args.custom:
	msg['Subject'] = 'Elb log report ' + args.custom
else:
	msg['Subject'] = 'Elb log report latency'
msg['From'] = 'ms@reancloud.com'
msg['To'] = args.email


########################################################################
#  Steps to download logs from s3 and return the logs as list          #
########################################################################



#function to select customer and returns cross account arn associates with client
def select_client(client):
	values = client.scan(TableName='AWS-ServiceLimit-Checker')['Items']
	print "\t\tSelect Customer\n*********************************************"
	i = 1
	for value in values:
		print str(i) + ". " + str(value['client']['S'])
		i += 1
	no = int(raw_input("Enter client Number: "))
	try:
		reply = raw_input( "You have selected " + str(values[no-1]['client']['S']) + ", do you want to continue(Y/N): ")
	except:
		print "Invalid Option"
		exit()
	if reply == 'y' or reply =='Y':
		return str(values[no-1]['crossaccountarn']['S'])
	else:
		exit()
#function to select region
def get_region(client):
	regions = client.describe_regions()['Regions']
	print "\t\tSelect Region\n***********************************************"
	i = 1
	values = []
	for region in regions:
		print str(i) + ". " + region['RegionName']
		i += 1
		values.append(region['RegionName'])
	no = int(raw_input("Enter region Number: "))
	if no not in range(1, len(values)+1):
		print "Invalid option"
		exit()
	reply = raw_input( "You have selected " + values[no-1] + ", do you want to continue(Y/N): ")
	if reply == 'y' or reply =='Y':
		return values[no-1]
	else:
		exit()
#function to select ELB
def get_elb(client):
	elbs = client.describe_load_balancers()['LoadBalancerDescriptions']
        print "\t\tSelect ELB\n***********************************************"
        i = 1
        values = []	
	for elb in elbs:
		print str(i) + ". " + elb['LoadBalancerName']
		i += 1
		values.append(elb['LoadBalancerName'])
	no = int(raw_input("Enter ELB Number: "))
	if no not in range(1, len(values)+1):
        	print "Invalid option"
 		exit()
	reply = raw_input( "You have selected " + values[no-1] + ", do you want to continue(Y/N): ")
	access_log = client.describe_load_balancer_attributes(LoadBalancerName=values[no-1])['LoadBalancerAttributes']['AccessLog']
	if access_log['Enabled'] != True:
		print "For " + values[no-1] + " access logs are not enabled"
		exit()
        if reply == 'y' or reply =='Y':
                return [access_log['S3BucketName'],access_log['S3BucketPrefix'], values[no-1]]
        else:
                exit()
#sub function to find list of s3 objects which got modified for last 2 hours
def s3_objects(client, s3_name, log_prefix, elb_name, start, end):
	s3_keys = []
	marker = ''
	while True:
		objects = client.list_objects(Bucket=s3_name, Prefix = log_prefix ,Marker = marker)
		try:
			for object in objects['Contents']:
				if object['LastModified'].strftime('%Y/%m/%d %H:%M:%S') >= start and object['LastModified'].strftime('%Y/%m/%d %H:%M:%S') <= end and object['Key'].split('_')[3] == elb_name:
					s3_keys.append(object['Key'])
				marker = object['Key']
		except:
			break
		if objects['IsTruncated']  == False:
			break
	return s3_keys
#function to get s3 log paths in a specified time frame
def log_path(path, start, end):
	pattern = re.compile("[0-9][0-9][0-9][0-9]/[0-9][0-9]/[0-9][0-9] [0-9][0-9]:[0-9][0-9]:[0-9][0-9]")
	if not pattern.match(start) and not pattern.match(end):
        	print "Entered start/end time is not in a proper format"
        	exit()
	prefix = []
	start1 = start.split(" ")[0]
	end1 = end.split(" ")[0]
	next1 = start1
	pattern = '%Y/%m/%d %H:%M:%S'
	epoch_start = int(calendar.timegm(time.strptime(start, pattern)))
	epoch_end = int(calendar.timegm(time.strptime(end, pattern)))
	epoch_next = epoch_start
	while end1>= next1:
        	prefix.append(path+next1)
        	epoch_next = epoch_next+24*3600
        	next1 = time.strftime("%Y/%m/%d", time.gmtime(epoch_next))
	return prefix
#function to get s3 file locations which got modified for last 2 hours
def log_files(client, s3_name, s3_prefix, account_id,region, elb_name):
	pattern = '%Y/%m/%d %H:%M:%S'
	if args.time == None:
		start = raw_input("Enter start date(YYYY/mm/dd HH:MM:SS) in UTC: ").strip()
		end = raw_input("Enter end date(YYYY/mm/dd HH:MM:SS) in UTC: ").strip()
	else:
		start = time.strftime('%Y/%m/%d %H:%M:%S', time.gmtime(time.time()-3600*args.time))
		end = time.strftime('%Y/%m/%d %H:%M:%S', time.gmtime(time.time()))
	temp_end = time.strftime('%Y/%m/%d %H:%M:%S',  time.gmtime((int(calendar.timegm(time.strptime(end, pattern)))+7200)))
	if s3_prefix:
		log_prefix = log_path(s3_prefix+'/AWSLogs/'+account_id+'/elasticloadbalancing/'+region+'/', start, temp_end)
	else:
		log_prefix = log_path('AWSLogs/'+account_id+'/elasticloadbalancing/'+region+'/', start , temp_end)
	s3_keys = []
	for i in log_prefix:
		s3_keys += s3_objects(client, s3_name, i, elb_name,start, temp_end)
	if len(s3_keys) == 0:
		print "There are no logs for the time you specified"
		exit()
	return [s3_keys, start, end]
#function to downlod s3 logs to a file and will return logs as a list
def get_logs(client, s3_name, s3_keys, elb_name, start, end):
	logs = []
	log_file = str(time.time())+'.log'
	for key in s3_keys:
		with open(log_file, 'ab') as data:
			client.download_fileobj(s3_name , key, data)
	with open(log_file,'rb') as data:
		for line in data:
			temp = line.split(" ")
			try:
				temp_time = temp[0].split('T')[0].replace('-','/') + ' '+ temp[0].split('T')[1].replace("Z","").split('.')[0]
				if temp_time >= start and temp_time <= end and elb_name == temp[1]:
					logs.append(line)
			except:
				continue
	os.remove(log_file)
	if len(logs) == 0:
		print "No logs are generated during the time frame"
		exit()
	else:
		print "There are "+str(len(logs))+ " logs generated."
	return logs


##############################################################################
#   Steps to parse the logs and generate output in a user specified format   #
##############################################################################

#function: select *(max(sort_column)) from list group_by(group_column) result will be in a sorted order and count will also added
def sort_group(check_list, sort_column, group_column):
        check_list = sorted(check_list, key=lambda x: (float(x[sort_column-1])), reverse=True)
        new_list = []
        temp_list = []
        for check in check_list:
                temp = check[group_column-1]
                if temp not in temp_list:
                        temp_list.append(temp)
                else:
                        continue
                count = 0
                for check1 in check_list:
                        if temp == check1[group_column-1]:
                                count += 1
                check.append(count)
                new_list.append(check)
        return new_list

#function to groupby elbstatus code and request url
def code_group(check_list, group1, group2, pattern):
	new_list = []
	temp_list = []
	for check in check_list:
		temp = check[group1-1]
		if temp not in temp_list and pattern.match(check[group2-1]):
			temp_list.append(temp)
		else:
			continue
		count = 0
		for check1 in check_list:
			if check1[group1-1] == temp and pattern.match(check1[group2-1]):
				count += 1
		check.append(count)
		new_list.append(check)
	return new_list
			

#function to print all fields in the log
def list_all_fields(logs):
	if args.output == None:
		print "Time_stamp\tclient:port\tbackend:port\tRequest_processing_time\tBackend_processing_time\tResponse_processing_time\tElb_status_code\tBackend_status_code\treceived_bytes\tsent_bytes\tRequest\tUser_agent\tssl_cipher\tssl_protocol"
		for log in logs:
			temp = log.split(" ")
			request = '-'
			user_agent = '-'
			try:
				request = re.findall(r'"([^"]*)"', log)[0]
				user_agent = re.findall(r'"([^"]*)"', log)[1]
			except:
				pass
			ssl_cipher = temp[len(temp)-1]
			ssl_protocol = temp[len(temp)-2]
			print temp[0]+'\t'+temp[1]+'\t'+temp[2]+'\t'+temp[3]+'\t'+temp[4]+'\t'+temp[5]+'\t'+temp[6]+'\t'+temp[7]+'\t'+temp[8]+'\t'+temp[9]+'\t'+temp[10]+'\t'+request+'\t'+user_agent+'\t'+ssl_cipher+'\t'+ssl_protocol
	else:
		with open(working_dir+args.output, "w") as f:
			f.write("Time_stamp\tclient:port\tbackend:port\tRequest_processing_time\tBackend_processing_time\tResponse_processing_time\tElb_status_code\tBackend_status_code\treceived_bytes\tsent_bytes\tRequest\tUser_agent\tssl_cipher\tssl_protocol")
                	for log in logs:
                        	temp = log.split(" ")
				request = '-'
				user_agent = '-'
				try:
                        		request = re.findall(r'"([^"]*)"', log)[0]
                        		user_agent = re.findall(r'"([^"]*)"', log)[1]
				except:
					pass	
                        	ssl_cipher = temp[len(temp)-1]
                        	ssl_protocol = temp[len(temp)-2]
                        	f.write(temp[0]+','+temp[1]+','+temp[2]+','+temp[3]+','+temp[4]+','+temp[5]+','+temp[6]+','+temp[7]+','+temp[8]+','+temp[9]+','+temp[10]+','+request+','+user_agent+','+ssl_protocol+ssl_cipher)
		

#function to print logs with followting fields.
#sl_no, source_ip, count_4xx group by sourceip and and sort by count
def list_statuscode(logs, pattern):
        logs_xx = []
	for log in logs:
                temp = log.split(" ")
                client_ip = temp[2].split(":")[0]
                logs_xx.append([client_ip, temp[7]])
        last = sorted(code_group(logs_xx, 1, 2, pattern), key=lambda x: (int(x[2]), x[0]), reverse=True)
	output = []
	for i in last:
		country = '-'
		org = '-'
		try:
			a = requests.get('http://ipinfo.io/'+i[0]).json()
			country = a['country']
			org = a['org']
		except:
			pass
		i.append(country)
		i.append(org)
		output.append(i)
        if args.output == None and args.email == None:
                print "Client_IP\tElb_status_code\tCount\tCountry_Code\tOrganisation"
                for i in output:
                        print i[0]+'\t'+i[1]+'\t'+str(i[2])+'\t'+i[3]+'\t'+i[4]
        elif args.output:
                with open(working_dir+args.output, "w") as f:
                        f.write("Client_IP,Elb_staus_code,Count,Country_code,Organisation\n")
                        for i in output:
                                f.write(i[0]+','+i[1]+','+str(i[2])+','+i[3]+','+i[4]+'\n')
	else:
		html = HTML.table(output, header_row = ['Client_IP','Elb_staus_code','Count','Country_code','Organisation'])
		part1 = MIMEText(html, 'html')
		msg.attach(part1)
		args.email
		s = smtplib.SMTP('localhost')
		s.sendmail('ms@reancloud.com', args.email, msg.as_string())
		s.quit()

#sl_no, source_ip, count_4xx group by sourceip and and sort by count
def parameter_4xx(logs):
        pattern = re.compile("4[0-9][0-9]")
        elb_statuscode = []
        for log in logs:
                temp = log.split(" ")
                elb_statuscode.append([temp[11]+" "+temp[12]+" "+temp[13],float(temp[4]),float(temp[5]),float(temp[6]),temp[7]])
        output = code_group(elb_statuscode,1,5,pattern)
        if args.output == None and args.email == None:
                print "Request_Url\tRequest_Processing_Time\tBackend_Processing_Time\tResponse_Processing_Time\tELB_Status_Code\tCount"
                for i in output:
                        print i[0]+'\t'+str(i[1])+'\t'+str(i[2])+'\t'+str(i[3])+'\t'+i[4]+'\t'+str(i[5])
        elif args.output:
                with open(working_dir+args.output, "w") as f:
                        f.write("Request_Url,Request_Processing_Time,Backend_Processing_Time,Response_Processing_Time,ELB_Status_Code,Count\n")
                        for i in output:
                                f.write(i[0]+','+str(i[1])+','+str(i[2])+','+str(i[3])+','+i[4]+','+str(i[5])+'\n')
	else:
		html = HTML.table(output, header_row = ['Request_Url','Request_Processing_Time','Backend_Processing_Time','Response_Processing_Time','ELB_Status_Code','Count'])
		part1 = MIMEText(html, 'html')
		msg.attach(part1)
		args.email
		s = smtplib.SMTP('localhost')
		s.sendmail('ms@reancloud.com', args.email, msg.as_string())
		s.quit()

#function to print logs with followting fields.
#sl_no, source_ip, count_5xx group by sourceip and and sort by count
def parameter_5xx(logs):
	pattern = re.compile("5[0-9][0-9]")
        elb_statuscode = []
	for log in logs:
                temp = log.split(" ")
                elb_statuscode.append([temp[11]+" "+temp[12]+" "+temp[13],float(temp[4]),float(temp[5]),float(temp[6]),temp[7]])
        output = code_group(elb_statuscode,1,5,pattern)
        if args.output == None and args.email == None:
		print "Request_Url\tRequest_Processing_Time\tBackend_Processing_Time\tResponse_Processing_Time\tELB_Status_Code\tCount"
                for i in output:
			print i[0]+'\t'+str(i[1])+'\t'+str(i[2])+'\t'+str(i[3])+'\t'+i[4]+'\t'+str(i[5])
        elif args.output:
                with open(working_dir+args.output, "w") as f:
                        f.write("Request_Url,Request_Processing_Time,Backend_Processing_Time,Response_Processing_Time,ELB_Status_Code,Count\n")
                        for i in output:
                                f.write(i[0]+','+str(i[1])+','+str(i[2])+','+str(i[3])+','+i[4]+','+str(i[5])+'\n')
	else:
		html = HTML.table(output, header_row = ['Request_Url','Request_Processing_Time','Backend_Processing_Time','Response_Processing_Time','ELB_Status_Code','Coiunt'])
		part1 = MIMEText(html, 'html')
		msg.attach(part1)
		args.email
		s = smtplib.SMTP('localhost')
		s.sendmail('ms@reancloud.com', args.email, msg.as_string())
		s.quit()

#function to print logs with following fields.
#Sl_no, request_time, back_time, resp_time
def parameter_latency(logs):
	latency = []
	for log in logs:
		temp = log.split(" ")
		latency.append([temp[11]+" "+temp[12]+" "+temp[13],float(temp[4]),float(temp[5]),float(temp[6]),temp[7]])
	output = sort_group(latency,3,1)
	if args.output == None and args.email == None:
		print "Request_Url\tRequest_Processing_Time\tBackend_Processing_Time\tResponse_Processing_Time\tELB_Status_Code\tCount"
		for i in output:
			print i[0]+'\t'+str(i[1])+'\t'+str(i[2])+'\t'+str(i[3])+'\t'+i[4]+'\t'+str(i[5])
	elif args.output:
		with open(working_dir+args.output, "w") as f:
			f.write("Request_Url,Request_Processing_Time,Backend_Processing_Time,Response_Processing_Time,ELB_Status_Code,Count\n")
			for i in output:
				f.write(i[0]+','+str(i[1])+','+str(i[2])+','+str(i[3])+','+i[4]+','+str(i[5])+'\n')
	else:
		html = HTML.table(output, header_row = ['Request_Url','Request_Processing_Time','Backend_Processing_Time','Response_Processing_Time','ELB_Status_Code','Count'])
		part1 = MIMEText(html, 'html')
		msg.attach(part1)
		args.email
		s = smtplib.SMTP('localhost')
		s.sendmail('ms@reancloud.com', args.email, msg.as_string())
		s.quit()

#Function to hand common option
#Output function1(console output)
def console_output(output):
	for raw in output:
		for element in raw:
			print element + '\t',
		print ''
#Output function2(file output)
def file_output(output):
	field = ''
	for raw in output:
		for element in raw:
			field = field+element+','
		field = field[:-1]
		field = field+'\n'
	with open(working_dir+args.output, "w") as f:
		f.write(field)
def email_output(output):
	headding = output[0]
	del output[0]
	html = HTML.table(output, header_row = headding)
	part1 = MIMEText(html, 'html')
	msg.attach(part1)
	args.email
	s = smtplib.SMTP('localhost')
	s.sendmail('ms@reancloud.com', args.email, msg.as_string())
	s.quit()
#grouping general function
def groupby_general(logs,fields):
        temp1_list = []  #temporary list1
        temp2_list = []  #temporary list2
        comp_list = []   #list for comparison
        final_list = []  #final list
        for log in logs:
                count = 0
                temp1_list = []
                for field in fields:
                        temp1_list.append(log[field])
                if temp1_list in comp_list:
                        continue
                comp_list.append(temp1_list)
                for log1 in logs:
                        temp2_list = []
                        for field in fields:
                                temp2_list.append(log1[field])
                        if temp1_list == temp2_list:
                                count += 1
                log.append(str(count))
                final_list.append(log)
        return final_list

#function to return an elb headding child funtion for list_custom
def elb_headding(fields):
	headding = []
	for field in fields:
		a = {
                	1 : 'Timestamp',
                	2 : 'ELB_Name',
                	3 : 'Client_IP',
			4 : 'Client_Port',
                	5 : 'Backend_IP',
			6 : 'Baackend_Port',
                	7 : 'Request_processing_time',
                	8 : 'Backend_processing_time',
                	9 : 'Response_processing_time',
                	10 : 'ELB_status_code',
                	11 : 'Backend_status_code',
                	12 : 'Received_Bytes',
                	13 : 'Sent Bytes',
                	14 : 'Request',
                	15 : 'User_Agent',
                	16 : 'SSL_cipher',
			17 : 'SSL_protocol',
			18 : 'Country_Code',
			19 : 'Organization'
		}[int(field)]
		headding.append(a)
	return headding

#function to list custom fields
def list_custom(logs,fields):
	fields = fields.split(',')
	req_output = []
	for log in logs:
		temp_output = []
		temp = log.split(' ')
		request = '-'
		user_agent = '-'
		try:
			request = re.findall(r'"([^"]*)"', log)[0]
			user_agent = re.findall(r'"([^"]*)"', log)[1]
		except:
			pass
		ssl_cipher = temp[len(temp)-1].strip()
		ssl_protocol = temp[len(temp)-2].strip()
		del temp[11:len(temp)]
		temp.append(request);temp.append(user_agent);temp.append(ssl_cipher);temp.append(ssl_protocol)
		client_ip = temp[2].split(':')[0]
		client_port = '-'
		try:
			client_port = temp[2].split(':')[1]
		except:
			pass
		temp[2] = client_ip
		temp.insert(3, client_port)
                backend_ip = temp[4].split(':')[0]
		backend_port = '-'
                try:
			backend_port = temp[4].split(':')[1]
		except:
			pass
                temp[4] = backend_ip
                temp.insert(5, backend_port)
		headding = elb_headding(fields)
		if '18' in fields or '19' in fields:
			country = '-'
			org = '-'
			try:
				a = requests.get('http://ipinfo.io/'+client_ip).json()
				temp.append(a['country'])
				temp.append(a['org'])
			except:
				pass
		for field in fields:
			temp_output.append(temp[int(field)-1])
		req_output.append(temp_output)
	#sortby option
	if args.sort_by:
		sortby_field = int(args.sort_by)
		if args.sort_by not in fields:
			print 'Specified sort field is not in custom field'
			exit()
		fields.index(sortby_field)
		req_output = sorted(req_output, key=lambda x: (float(x[fields.index(sortby_field)])), reverse=True)
	#groupby option
	temp_groups = []
	if args.group_by:
		group_fields = args.group_by.split(',')
		if set(group_fields) <= set(fields):
			for group_field in group_fields:
				for field in fields:
					if field == group_field:
						temp_groups.append(fields.index(group_field))
		else:
			print 'Group_by option is not a subset of custom option(Error)'
			exit()	
		req_output = groupby_general(req_output, temp_groups)
		if not args.sort_by:
			req_output = sorted(req_output, key=lambda x: (float(x[len(fields)])), reverse=True)
		headding.append('Count')
	req_output.insert(0,headding)
	return req_output


################################################################################
#                             main function                                    # 
################################################################################
#Getting elb logs for the time specified
def main():
	cross_role = select_client(boto3.client('dynamodb','us-west-2'))
	account_id = cross_role.split(':')[4]
	region = get_region(boto3.client('ec2'))
	assume_role = boto3.client('sts').assume_role(RoleArn=cross_role,RoleSessionName='Demo')
	access_key = assume_role['Credentials']['AccessKeyId']
	secret_key = assume_role['Credentials']['SecretAccessKey']
	session_token = assume_role['Credentials']['SessionToken']
	client = boto3.client('elb',region_name=region,aws_access_key_id=access_key,aws_secret_access_key=secret_key,aws_session_token=session_token)
	log_location = get_elb(client)
	client = boto3.client('s3', aws_access_key_id=access_key,aws_secret_access_key=secret_key,aws_session_token=session_token)
	s3_keys = log_files(client, log_location[0], log_location[1], account_id, region, log_location[2])
	logs = get_logs(client, log_location[0], s3_keys[0], log_location[2], s3_keys[1], s3_keys[2])

	if args.result and args.custom:
		print "Both custom and result can't use simultaniously"
	elif args.result=='latency' or (not args.result and not args.custom):
		parameter_latency(logs)
	elif args.result=='5xx':
		parameter_5xx(logs)
	elif args.result=='4xx':
		parameter_4xx(logs)
	elif args.result=='all':
		list_all_fields(logs)
	elif args.result=='source_4xx':
		list_statuscode(logs,re.compile("4[0-9][0-9]"))
	elif args.result=='source_5xx':
        	list_statuscode(logs, re.compile("5[0-9][0-9]"))
	elif args.result=='source_3xx':
        	list_statuscode(logs,re.compile("3[0-9][0-9]"))
	elif args.result=='source_2xx':
        	list_statuscode(logs,re.compile("2[0-9][0-9]"))
	elif args.result=='invalid':
        	list_statuscode(logs,re.compile("^-$"))
	elif args.custom:
		if args.output == None and args.email == None:
			console_output(list_custom(logs,args.custom))
		elif args.output:
			file_output(list_custom(logs,args.custom))
		else:
			email_output(list_custom(logs,args.custom))			
	else:
		print "Wrong option given."


if __name__ == '__main__':
    main()
#End of main function
