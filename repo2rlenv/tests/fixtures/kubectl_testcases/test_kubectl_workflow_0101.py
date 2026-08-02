from kubernetes import client


def test_workflow_0101_deployment_scale_cycle(cli, k8s_client, kubectl_bin, tmp_path):
    mfile = tmp_path / "m.yaml"
    mfile.write_text('apiVersion: apps/v1\nkind: Deployment\nmetadata:\n  name: wf-dep-0101\n  namespace: default\nspec:\n  replicas: 1\n  selector:\n    matchLabels:\n      app: wf-dep-0101\n  template:\n    metadata:\n      labels:\n        app: wf-dep-0101\n    spec:\n      containers: [{name: c, image: nginx}]\n')
    r_apply = cli("apply", "-f", str(mfile))
    assert r_apply.returncode == 0, r_apply.stderr
    r_up = cli("scale", "deployment", "wf-dep-0101", "--replicas=2", "-n", "default")
    assert r_up.returncode == 0, r_up.stderr
    up = client.AppsV1Api(k8s_client.api_client).read_namespaced_deployment(name="wf-dep-0101", namespace="default")
    assert up.spec.replicas == 2
    r_down = cli("scale", "deployment", "wf-dep-0101", "--replicas=1", "-n", "default")
    assert r_down.returncode == 0, r_down.stderr
    r_del = cli("delete", "deployment", "wf-dep-0101", "-n", "default")
    assert r_del.returncode == 0, r_del.stderr
