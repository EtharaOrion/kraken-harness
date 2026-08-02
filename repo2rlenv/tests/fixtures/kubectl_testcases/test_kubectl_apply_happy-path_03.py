from kubernetes import client


def test_apply_deployment_manifest_creates_deployment(cli, k8s_client, tmp_path):
    dep_name = f"dep-apply-hp03-{tmp_path.name.replace('_', '-').lower()[:30]}"
    manifest = tmp_path / f"{dep_name}.yaml"
    manifest.write_text(
        f"apiVersion: apps/v1\nkind: Deployment\nmetadata:\n  name: {dep_name}\n  namespace: default\n"
        f"spec:\n  replicas: 1\n  selector: {{matchLabels: {{app: {dep_name}}}}}\n"
        f"  template:\n    metadata: {{labels: {{app: {dep_name}}}}}\n"
        "    spec:\n      containers: [{name: c, image: nginx}]\n"
    )
    result = cli("apply", "-f", str(manifest))
    assert result.returncode == 0, result.stderr
    assert f"deployment.apps/{dep_name}" in result.stdout
    assert "created" in result.stdout or "configured" in result.stdout
    apps_v1 = client.AppsV1Api(k8s_client.api_client)
    dep = apps_v1.read_namespaced_deployment(name=dep_name, namespace="default")
    assert dep.metadata.name == dep_name
