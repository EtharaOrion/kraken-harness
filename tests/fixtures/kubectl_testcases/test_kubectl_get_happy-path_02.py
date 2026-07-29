def test_get_pods_lists_all(cli, k8s_client, kubectl_bin, tmp_path):
    names = ["get-hp02-a", "get-hp02-b"]
    for n in names:
        pod = tmp_path / f"{n}.yaml"
        pod.write_text(
            f"apiVersion: v1\nkind: Pod\nmetadata:\n  name: {n}\n  namespace: default\n"
            "spec:\n  containers: [{name: c, image: nginx}]\n"
        )
        seed = kubectl_bin(["apply", "-f", str(pod)])
        assert seed.returncode == 0, seed.stderr
    result = cli("get", "pods", "-n", "default")
    assert result.returncode == 0, result.stderr
    assert "get-hp02-a" in result.stdout
    assert "get-hp02-b" in result.stdout
    pods = {p.metadata.name for p in k8s_client.list_namespaced_pod(namespace="default").items}
    assert "get-hp02-a" in pods and "get-hp02-b" in pods
