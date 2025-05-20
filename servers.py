def create_servers(conn, server_name, port_name, image_id, flavor_id, keypair_name, security_group_id, network_id, floating_ip_required,existing_servers): 
    if server_name in existing_servers:
        server = conn.compute.find_server(server_name)
        port = conn.network.find_port(port_name)
        fip = get_floating_ip(server.addresses) if floating_ip_required else None
        print(f"{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')} Server {server_name} already exists. {fip}, {port_name}")
        return server, fip
    else:
        port = conn.network.create_port(name=port_name, network_id=network_id,security_groups=[security_group_id])
        print(f"{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')} Created port {port.name} with ID {port.id}.")
        server = conn.compute.create_server(name=server_name, image_id=image_id, flavor_id=flavor_id, key_name=keypair_name,networks=[{"port": port.id}])
        server = conn.compute.wait_for_server(server)
        print(f"{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')} Server {server.name}")
        applied_security_groups = [sg['name'] for sg in server.security_groups]
        print(f"{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')} Applied security groups: {applied_security_groups}")

        if floating_ip_required:
            fip_tuple = create_floating_ip(conn, "ext-net")
            associate_floating_ip(conn, server_name, fip_tuple)
            fip = fip_tuple[2]
            print(f"{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')} Server {server.name} assigned floating IP {fip}.")
        else:
            fip = None
        return server, fip

def manage_dev_servers(conn, existing_servers, tag_name, image_id, flavor_id, keypair_name, security_group_name, network_id):
    dev_ips = {}
    dev_server = f"{tag_name}_dev"
    dev_port_name = f"{tag_name}_dev_port"
    required_dev_servers = 3
    devservers_count = len([line for line in existing_servers.splitlines() if dev_server in line])
    print(f"{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')} Will need {required_dev_servers} node, launching them.")        
    dev_servers = conn.compute.servers(details=True, all_projects=False, filters={"name": f"{dev_server}*"})
    for server in dev_servers:
        if network_id in server.addresses and server.addresses[network_id]:
            internal_ip = server.addresses[network_id][0]['addr']
            dev_ips[server.name] = internal_ip
            print(f"Existing server {server.name} with IP {internal_ip} added to dev_ips")

    if required_dev_servers > devservers_count:
        devservers_to_add = required_dev_servers - devservers_count
        sequence = devservers_count + 1
        while devservers_to_add > 0:
            devserver_name = f"{dev_server}{sequence}"
            dev_port_n = f"{dev_port_name}{sequence}"
            server, _ = create_servers(conn, devserver_name, dev_port_n, image_id, flavor_id, keypair_name, security_group_name, network_id, False, existing_servers)
            if network_id in server.addresses and server.addresses[network_id]:
                internal_ip = server.addresses[network_id][0]['addr']
                dev_ips[devserver_name] = internal_ip
            devservers_to_add -= 1
            sequence += 1
    elif required_dev_servers < devservers_count:
        devservers_to_remove = devservers_count - required_dev_servers
        servers = list(conn.compute.servers(details=True, status='ACTIVE', name=f"{tag_name}_dev"))
        for _ in range(devservers_to_remove):
            if servers:
                server_to_delete = servers[0]
                conn.compute.delete_server(server_to_delete.id)
                print(f"{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')} Deleted {server_to_delete.name} server")
    else:
        print(f"Required number of dev servers({required_dev_servers}) already exist.")
    
    return dev_ips

def create_vip_port(conn, network_id, subnet_id, tag_name, server_name, security_group_id, existing_port):
    vip_port_name = f"{tag_name}_vip_port"
    existing_port = conn.network.find_port(vip_port_name)
    if existing_port:
        print(f"{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')} VIP port {vip_port_name} already exists with ID {existing_port.id}.")
        return existing_port
    vip_port = conn.network.create_port(name=vip_port_name, network_id=network_id,security_groups=[security_group_id])
    print(f"{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')} Created VIP port {vip_port_name} with ID {vip_port.id}{security_group_id}.")
    return vip_port

def assign_floating_ip_to_port(conn, vip_port):
    if vip_port is None:
        print(f"{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')} VIP port is None, cannot assign floating IP.")
        return None
    existing_floating_ips = list(conn.network.ips(port_id=vip_port.id))
    if existing_floating_ips:
        existing_floating_ip = existing_floating_ips[0]
        print(f"{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')} VIP port {vip_port.id} already has floating IP {existing_floating_ip.floating_ip_address}.")
        return existing_floating_ip.floating_ip_address, existing_floating_ip.id
    floating_ip_tuple = create_floating_ip(conn, "ext-net")
    if floating_ip_tuple[1] is None:
        print(f"{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')} Failed to create floating IP.")
        return None
    conn.network.update_ip(floating_ip_tuple[1], port_id=vip_port.id)
    print(f"{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')} Associated floating IP {floating_ip_tuple[2]} with port {vip_port.id}.")
    return floating_ip_tuple[2], floating_ip_tuple[1]

def attach_port_to_server(conn, server_name, vip_port):
    server_instance = conn.compute.find_server(server_name)
    server_interfaces = conn.compute.server_interfaces(server_instance)
    for interface in server_interfaces:
        if interface.port_id == vip_port.id:
            print(f"{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')} VIP port {vip_port.id} is already attached to instance,{server_instance.name}.")
            return
    conn.compute.create_server_interface(
        server=server_instance.id,
        port_id=vip_port.id
    )
    print(f"{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')} Attached VIP port {vip_port.id} to instance {server_instance.name}.")

def generate_vip_addresses_file(vip_floating_ip_haproxy2):
    ip_address, _ = vip_floating_ip_haproxy2
    with open("vip_address", "w") as f:
        f.write(f"{ip_address}\n")
    return 

def generate_servers_ip_file(server_fip_map, file_path):
    with open(file_path, 'w') as f:
        for server, fip in server_fip_map.items():
            f.write(f"{server}:{fip}\n")
    print(f"{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')} Generated servers_fips file at {file_path}.")
    return file_path

def generate_configs(tag_name, private_key):
    print("Genrating Configuration files.")
    output = run_command(f"python3 scripts/gen_config.py {tag_name} {private_key}")
    print(output)
    return output

def run_ansible_playbook():
    print("Running Ansible playbook...")
    ansible_command = "ansible-playbook -i hosts scripts/site.yaml"
    subprocess.run(ansible_command, shell=True)

def main(rc_file, tag_name, private_key):
    current_date_time = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    print(f"{current_date_time} Starting deployment of {tag_name} using {rc_file} for credentials.")
    
    with open(rc_file) as f:
        for line in f:
            if line.strip() and not line.startswith('#'):
                key, value = line.split('=', 1)
                os.environ[key.strip()] = value.strip()
    
    conn = connect_to_openstack()
    network_name = f"{tag_name}_network"
    subnet_name = f"{tag_name}_subnet"
    router_name = f"{tag_name}_router"
    security_group_name = f"{tag_name}_security_group"
    keypair_name = f"{tag_name}_key"
    bastion_name = f"{tag_name}_bastion"
    bastion_port_name = f"{tag_name}_bastion_port"
    haproxy_name = f"{tag_name}_HAproxy"
    haproxy_port_name = f"{tag_name}_HAproxy_port"
    haproxy2_name = f"{tag_name}_HAproxy2"
    haproxy2_port_name = f"{tag_name}_HAproxy2_port"
    

    create_keypair(conn, keypair_name, private_key)
    network_id, subnet_id = setup_network(conn, tag_name, network_name, subnet_name, router_name, security_group_name)   
    uuids = fetch_server_uuids(conn, "Ubuntu 20.04 Focal Fossa x86_64", "1C-2GB-50GB",security_group_name)
    existing_servers, _ = run_command("openstack server list --status ACTIVE --column Name -f value")
    bastion_server, bastion_fip = create_servers(conn,bastion_name,bastion_port_name,uuids['image_id'],uuids['flavor_id'],keypair_name,uuids['security_group_id'],network_id,True,existing_servers)
    haproxy_server, haproxy_fip = create_servers(conn, haproxy_name, haproxy_port_name, uuids['image_id'],uuids['flavor_id'],keypair_name,uuids['security_group_id'],network_id,True,existing_servers)
    haproxy2_server, haproxy2_fip = create_servers(conn, haproxy2_name, haproxy2_port_name, uuids['image_id'],uuids['flavor_id'],keypair_name,uuids['security_group_id'],network_id,True,existing_servers)
    fip_map = {
        bastion_name: bastion_fip,
        haproxy_name: haproxy_fip,
        haproxy2_name: haproxy2_fip
    }    
    generate_servers_ip_file(fip_map, "servers_fip")
    manage_dev_servers(conn, existing_servers, tag_name, uuids['image_id'], uuids['flavor_id'], keypair_name, uuids["security_group_id"], network_id)
    existing_ports = conn.network.ports()
    vip_port_haproxy2 = create_vip_port(conn, network_id, subnet_id, tag_name, haproxy2_server.id,uuids["security_group_id"] ,existing_ports)
    attach_port_to_server(conn, haproxy2_server.id, vip_port_haproxy2)
    vip_floating_ip_haproxy2 = assign_floating_ip_to_port(conn, vip_port_haproxy2)
    generate_vip_addresses_file(vip_floating_ip_haproxy2)
    print(f"{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')} Deployment of {tag_name} completed.")

if __name__ == "__main__":
    if len(sys.argv) != 4:
        print("Usage: python install.py <rc_file> <tag_name> <public_key>")
        sys.exit(1)    
    rc_file = sys.argv[1]
    tag_name = sys.argv[2]
    public_key = sys.argv[3]
    main(rc_file, tag_name, public_key)
