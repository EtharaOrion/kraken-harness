def test_delete_service_0007_by_name(cli, k8s_client, kubectl_bin, tmp_path):
    manifest = tmp_path / "m.yaml"
    manifest.write_text('apiVersion: v1\nkind: Service\nmetadata:\n  name: dse-0007\n  namespace: default\nspec:\n  selector: {app: demo}\n  ports: [{port: 80, targetPort: 80}]\n')
    seed = kubectl_bin(["apply", "-f", str(manifest)])
    assert seed.returncode == 0, seed.stderr
    result = cli("delete", "service", "dse-0007", "-n", "default")
    assert result.returncode == 0, result.stderr
    names = {o.metadata.name for o in k8s_client.list_namespaced_service(namespace="default").items}
    assert "dse-0007" not in names
