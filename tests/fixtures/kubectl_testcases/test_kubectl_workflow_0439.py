def test_workflow_0439_service_lifecycle(cli, kubectl_bin, tmp_path, k8s_client):
    mfile = tmp_path / "m.yaml"
    mfile.write_text('apiVersion: v1\nkind: Service\nmetadata:\n  name: wf-svc-0439\n  namespace: default\nspec:\n  selector: {app: demo}\n  ports: [{port: 80, targetPort: 80}]\n')
    r_apply = cli("apply", "-f", str(mfile))
    assert r_apply.returncode == 0, r_apply.stderr
    r_get = cli("get", "service", "wf-svc-0439", "-n", "default", "-o", "yaml")
    assert r_get.returncode == 0, r_get.stderr
    r_desc = cli("describe", "service", "wf-svc-0439", "-n", "default")
    assert r_desc.returncode == 0, r_desc.stderr
    r_del = cli("delete", "service", "wf-svc-0439", "-n", "default")
    assert r_del.returncode == 0, r_del.stderr
