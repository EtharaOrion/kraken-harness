def test_patch_limitrange_0029_json(cli, kubectl_bin, tmp_path):
    manifest = tmp_path / "m.yaml"
    manifest.write_text('apiVersion: v1\nkind: LimitRange\nmetadata:\n  name: pli-0029\n  namespace: default\nspec:\n  limits:\n  - type: Container\n    default: {cpu: 100m}\n    defaultRequest: {cpu: 50m}\n')
    seed = kubectl_bin(["apply", "-f", str(manifest)])
    assert seed.returncode == 0, seed.stderr
    result = cli("patch", "limitrange", "pli-0029", "-n", "default", "--type=json", "-p", '[{"op":"add","path":"/metadata/labels/lane","value":"c29"}]')
    assert result.returncode == 0, result.stderr
    assert "pli-0029" in result.stdout
