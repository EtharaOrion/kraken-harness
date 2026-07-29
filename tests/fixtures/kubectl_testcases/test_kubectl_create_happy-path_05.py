def test_create_service_clusterip_succeeds(cli, k8s_client, kubectl_bin, tmp_path):
    svc_name = f"svc-cr-hp05-{tmp_path.name.replace('_', '-').lower()[:30]}"
    result = cli("create", "service", "clusterip", svc_name, "--tcp=80:80", "-n", "default")
    assert result.returncode == 0, result.stderr
    services = k8s_client.list_namespaced_service(namespace="default").items
    assert any(s.metadata.name == svc_name for s in services)
