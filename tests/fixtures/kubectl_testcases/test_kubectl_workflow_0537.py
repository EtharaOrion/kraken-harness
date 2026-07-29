def test_workflow_0537_bulk_pods_by_selector(cli, kubectl_bin, k8s_client, tmp_path):
    m1 = tmp_path / "a.yaml"
    m1.write_text('apiVersion: v1\nkind: Pod\nmetadata:\n  name: wf-mp-a-0537\n  namespace: default\n  labels:\n    batch: "sel-0537"\nspec:\n  containers: [{name: c, image: nginx}]\n')
    m2 = tmp_path / "b.yaml"
    m2.write_text('apiVersion: v1\nkind: Pod\nmetadata:\n  name: wf-mp-b-0537\n  namespace: default\n  labels:\n    batch: "sel-0537"\nspec:\n  containers: [{name: c, image: nginx}]\n')
    m3 = tmp_path / "c.yaml"
    m3.write_text('apiVersion: v1\nkind: Pod\nmetadata:\n  name: wf-mp-c-0537\n  namespace: default\n  labels:\n    batch: "sel-0537"\nspec:\n  containers: [{name: c, image: nginx}]\n')
    for m in (m1, m2, m3):
        seed = kubectl_bin(["apply", "-f", str(m)])
        assert seed.returncode == 0, seed.stderr
    r_get = cli("get", "pods", "-l", "batch=sel-0537", "-n", "default")
    assert r_get.returncode == 0, r_get.stderr
    r_lab = cli("label", "pods", "-l", "batch=sel-0537", "tier=x", "-n", "default")
    assert r_lab.returncode == 0, r_lab.stderr
    r_del = cli("delete", "pods", "-l", "batch=sel-0537", "-n", "default")
    assert r_del.returncode == 0, r_del.stderr
    pods = k8s_client.list_namespaced_pod(namespace="default").items
    assert not any(p.metadata.labels and p.metadata.labels.get("batch") == "sel-0537" for p in pods)
