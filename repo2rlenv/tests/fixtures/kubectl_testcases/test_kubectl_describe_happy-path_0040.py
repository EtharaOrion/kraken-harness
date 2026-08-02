def test_describe_ingress_0040_show_events(cli, kubectl_bin, tmp_path):
    manifest = tmp_path / "m.yaml"
    manifest.write_text('apiVersion: networking.k8s.io/v1\nkind: Ingress\nmetadata:\n  name: esin-0040\n  namespace: default\nspec:\n  rules:\n  - host: example.local\n    http:\n      paths:\n      - path: /\n        pathType: Prefix\n        backend:\n          service:\n            name: demo\n            port: {number: 80}\n')
    seed = kubectl_bin(["apply", "-f", str(manifest)])
    assert seed.returncode == 0, seed.stderr
    result = cli("describe", "ingress", "esin-0040", "-n", "default", "--show-events=true")
    assert result.returncode == 0, result.stderr
    assert "esin-0040" in result.stdout
