def test_describe_service_shows_endpoints(cli, k8s_client, kubectl_bin, tmp_path):
    svc_name = "svc-hp04"
    manifest = tmp_path / "svc.yaml"
    manifest.write_text(
        f"apiVersion: v1\nkind: Service\nmetadata:\n  name: {svc_name}\n  namespace: default\n"
        "spec:\n  selector: {app: hp04}\n  ports: [{port: 80, targetPort: 80}]\n"
    )
    seed = kubectl_bin(["apply", "-f", str(manifest)])
    assert seed.returncode == 0, seed.stderr
    result = cli("describe", "service", svc_name, "-n", "default")
    assert result.returncode == 0, result.stderr
    assert svc_name in result.stdout
    assert "Selector:" in result.stdout
    assert "Port:" in result.stdout
    svcs = k8s_client.list_namespaced_service(namespace="default").items
    assert any(s.metadata.name == svc_name for s in svcs)
