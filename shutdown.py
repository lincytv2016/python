import boto3
import pprint
import pdb
regions = ["ap-south-1"]#, "us-east-1", "eu-west-1", "sa-east-1", "us-west-1", "ap-southeast-1", "ap-southeast-2",  "us-west-2"]
def lambda_handler(event,context):
	for i in regions:
		ec3=boto3.resource('ec2',region_name=i)
		ec2=boto3.client('ec2',region_name=i)
		response = ec2.describe_instances()
		if len(response['Reservations'])>0:
			for resp in response['Reservations']:
				if resp['Instances'][0]['State']['Name'] == 'running':
					k=(resp['Instances'][0]['InstanceId'])
					print "stopting the instance with ID : "+k
					ec3.instances.filter(InstanceIds=[k]).stop()