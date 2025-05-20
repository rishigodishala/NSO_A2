#!/usr/bin/python3

import datetime
import time
import os
import sys
import openstack
import subprocess
from openstack import connection


def run_command(command):
    result = subprocess.run(command, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    return result.stdout.decode().strip(), result.stderr.decode().strip()
    
def connect_to_openstack():
    return openstack.connect(
        auth_url=os.getenv('OS_AUTH_URL'),
        project_name=os.getenv('OS_PROJECT_NAME'),
        username=os.getenv('OS_USERNAME'),
        password=os.getenv('OS_PASSWORD'),
        user_domain_name=os.getenv('OS_USER_DOMAIN_NAME'),
        project_domain_name=os.getenv('OS_PROJECT_DOMAIN_NAME')
    )

def extract_public_key(private_key_path):
    public_key_path = private_key_path + '.pub'
    if not os.path.exists(public_key_path):
        command = f"ssh-keygen -y -f {private_key_path} > {public_key_path}"
        subprocess.run(command, shell=True, check=True)
    with open(public_key_path, 'r') as file:
        public_key = file.read().strip()
    return public_key

def create_keypair(conn, keypair_name, private_key_path):
    keypair = conn.compute.find_keypair(keypair_name)
    current_date_time = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    print(f"{current_date_time} Checking for keypair {keypair_name}.")
    if not keypair:
        public_key = extract_public_key(private_key_path)
        keypair = conn.compute.create_keypair(name=keypair_name, public_key=public_key)
        print(f"{current_date_time} Created keypair {keypair_name}.")
        uploaded_keypair = conn.compute.find_keypair(keypair_name)
        if uploaded_keypair and uploaded_keypair.public_key == public_key:
            print(f"{current_date_time} Verified keypair {keypair_name} was uploaded successfully.")
        else:
            print(f"{current_date_time} Failed to verify keypair {keypair_name}.")
    else:
        print(f"{current_date_time} Keypair {keypair_name} already exists.")
    return keypair.id

def setup_network(conn, tag_name, network_name, subnet_name, router_name, security_group_name):
    network = conn.network.find_network(network_name)
    if not network:
        network = conn.network.create_network(name=network_name)
        print(f"{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')} Created network {network_name}.{network.id}")
        network_id = network.id
    else:
        network = conn.network.find_network(network_name)
        network_id = network.id
        print(f"{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')} Network {network_name}.{network_id} already exists.")

    subnet = conn.network.find_subnet(subnet_name)
    if not subnet:
        subnet = conn.network.create_subnet(
            name=subnet_name, network_id=network.id, ip_version=4, cidr='10.10.0.0/24',
            allocation_pools=[{'start': '10.10.0.2', 'end': '10.10.0.30'}])
        subnet_id = subnet.id
        print(f"{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')} Created subnet {subnet_name}.{subnet.id}")
    else:
        subnet = conn.network.find_subnet(subnet_name)
        subnet_id = subnet.id
        print(f"{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')} Subnet {subnet_name}.{subnet_id} already exists.")
        
    router = conn.network.find_router(router_name)
    if not router:
        router = conn.network.create_router(name=router_name, external_gateway_info={'network_id': conn.network.find_network('ext-net').id})
        conn.network.add_interface_to_router(router, subnet_id=subnet.id)
        print(f"{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')} Created router {router_name} and attached subnet {subnet_name}.")
    else:
        router = conn.network.find_router(router_name)
        print(f"{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')} Router {router_name} already exists.")

    security_group = conn.network.find_security_group(security_group_name)
    if not security_group:
        security_group = conn.network.create_security_group(name=security_group_name)
        rules = [
            {"protocol": "tcp", "port_range_min": 22, "port_range_max": 22, "remote_ip_prefix": "0.0.0.0/0"},
            {"protocol": "icmp", "remote_ip_prefix": "0.0.0.0/0"},
            {"protocol": "tcp", "port_range_min": 80, "port_range_max": 80, "remote_ip_prefix": "0.0.0.0/0"},
            {"protocol": "tcp", "port_range_min": 5000, "port_range_max": 5000, "remote_ip_prefix": "0.0.0.0/0"},
            {"protocol": "tcp", "port_range_min": 8080, "port_range_max": 8080, "remote_ip_prefix": "0.0.0.0/0"},
            {"protocol": "udp", "port_range_min": 6000, "port_range_max": 6000, "remote_ip_prefix": "0.0.0.0/0"},
            {"protocol": "tcp", "port_range_min": 9090, "port_range_max": 9090, "remote_ip_prefix": "0.0.0.0/0"},
            {"protocol": "tcp", "port_range_min": 9100, "port_range_max": 9100, "remote_ip_prefix": "0.0.0.0/0"},
            {"protocol": "tcp", "port_range_min": 3000, "port_range_max": 3000, "remote_ip_prefix": "0.0.0.0/0"},
            {"protocol": "udp", "port_range_min": 161, "port_range_max": 161, "remote_ip_prefix": "0.0.0.0/0"},
            {"protocol": 112, "remote_ip_prefix": "0.0.0.0/0"}  # VRRP protocol
        ]
        for rule in rules:
            conn.network.create_security_group_rule(
                security_group_id=security_group.id,direction='ingress', protocol=rule['protocol'],port_range_min=rule.get('port_range_min'),  port_range_max=rule.get('port_range_max'), remote_ip_prefix=rule['remote_ip_prefix'])
        print(f"{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')} Created security group {security_group_name} with rules.")
    else:
        security_group = conn.network.find_security_group(security_group_name)
        print(f"{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')} Security group {security_group_name} already exists{security_group.id}")  
    return network_id, subnet_id

def wait_for_active_state(server, retries=5, delay=30):
    for _ in range(retries):
        status, _ = run_command(f"openstack server show {server} -c status -f value")
        if status.strip() == "ACTIVE":
            return True
        time.sleep(delay)
    return False

def wait_for_network_ready(server, retries=5, delay=30):
    for _ in range(retries):
        net_status, _ = run_command(f"openstack server show {server} -c addresses -f value")
        if net_status.strip():
            return True
        time.sleep(delay)
    return False

def create_floating_ip(conn, network_name):
    floating_ips = conn.network.ips(floating_network_id=network_name)
    for floating_ip in floating_ips:
        if not floating_ip.port_id:
            return  floating_ip.id, floating_ip.floating_ip_address
    external_network = conn.network.find_network(network_name)
    if not external_network:
        raise Exception(f"Network {network_name} not found")
    floating_ip = conn.network.create_ip(floating_network_id=external_network.id)
    return floating_ip,floating_ip.id, floating_ip.floating_ip_address

def associate_floating_ip(conn, server, floating_ip_tuple):
    floating_ip, floating_ip_id, floating_ip_address = floating_ip_tuple
    server_instance = conn.compute.find_server(server)
    if not server_instance:
        raise Exception(f"Server {server} not found")
    server_port = list(conn.network.ports(device_id=server_instance.id))
    if not server_port:
        raise Exception(f"Port not found for server {server}")
    server_port = server_port[0]
    conn.network.update_ip(floating_ip_id, port_id=server_port.id)
    return floating_ip

def fetch_server_uuids(conn, image_name, flavor_name, security_group_name):
    image = conn.compute.find_image(image_name)
    if not image:
        raise Exception(f"Image {image_name} not found")
    image_id = image.id
    
    flavor = conn.compute.find_flavor(flavor_name)
    if not flavor:
        raise Exception(f"Flavor {flavor_name} not found")
    flavor_id = flavor.id
    
    security_group = conn.network.find_security_group(security_group_name)
    if not security_group:
        raise Exception(f"Security group {security_group_name} not found")
    security_group_id = security_group.id
    return {'image_id': image_id, 'flavor_id': flavor_id, 'security_group_id': security_group_id}

def get_floating_ip(addresses):
    for network, address_list in addresses.items():
        for address in address_list:
            if address['OS-EXT-IPS:type'] == 'floating':
                return address['addr']
    return None
