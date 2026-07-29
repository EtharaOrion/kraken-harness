def test_label_pod_0304_overwrite(cli, kubectl_bin, k8s_client, tmp_path):
    manifest = tmp_path / "m.yaml"
    manifest.write_text('apiVersion: v1\nkind: Pod\nmetadata:\n  name: lo-0304\n  namespace: default\n  labels:\n    role: "old"\nspec:\n  containers: [{name: c, image: nginx}]\n')
    seed = kubectl_bin(["apply", "-f", str(manifest)])
    assert seed.returncode == 0, seed.stderr
    result = cli("label", "pod", "lo-0304", "role=new", "--overwrite", "-n", "default")
    assert result.returncode == 0, result.stderr
    pod = next(p for p in k8s_client.list_namespaced_pod(namespace="default").items if p.metadata.name == "lo-0304")
    assert pod.metadata.labels.get("role") == "new"
