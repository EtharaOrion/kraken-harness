def test_label_pods_0421_by_selector(cli, kubectl_bin, k8s_client, tmp_path):
    m1 = tmp_path / "a.yaml"
    m1.write_text('apiVersion: v1\nkind: Pod\nmetadata:\n  name: lm-a-0421\n  namespace: default\n  labels:\n    group: "g0421"\nspec:\n  containers: [{name: c, image: nginx}]\n')
    m2 = tmp_path / "b.yaml"
    m2.write_text('apiVersion: v1\nkind: Pod\nmetadata:\n  name: lm-b-0421\n  namespace: default\n  labels:\n    group: "g0421"\nspec:\n  containers: [{name: c, image: nginx}]\n')
    seed1 = kubectl_bin(["apply", "-f", str(m1)])
    assert seed1.returncode == 0, seed1.stderr
    seed2 = kubectl_bin(["apply", "-f", str(m2)])
    assert seed2.returncode == 0, seed2.stderr
    result = cli("label", "pods", "-l", "group=g0421", "batch=true", "-n", "default")
    assert result.returncode == 0, result.stderr
    pods = [p for p in k8s_client.list_namespaced_pod(namespace="default").items if p.metadata.labels and p.metadata.labels.get("group") == "g0421"]
    for p in pods:
        assert p.metadata.labels.get("batch") == "true"
