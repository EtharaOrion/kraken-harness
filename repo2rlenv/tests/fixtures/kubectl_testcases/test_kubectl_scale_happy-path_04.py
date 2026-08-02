from kubernetes import client


def test_scale_replicationcontroller_up_to_four(cli, k8s_client, kubectl_bin):
    kubectl_bin(["create", "namespace", "scale-rc-hp04"])
    rc = client.V1ReplicationController(
        metadata=client.V1ObjectMeta(name="r-hp04", namespace="scale-rc-hp04"),
        spec=client.V1ReplicationControllerSpec(
            replicas=1,
            selector={"app": "r-hp04"},
            template=client.V1PodTemplateSpec(
                metadata=client.V1ObjectMeta(labels={"app": "r-hp04"}),
                spec=client.V1PodSpec(containers=[client.V1Container(name="c", image="nginx")]),
            ),
        ),
    )
    k8s_client.create_namespaced_replication_controller(namespace="scale-rc-hp04", body=rc)
    result = cli("scale", "rc", "r-hp04", "--replicas=4", "-n", "scale-rc-hp04")
    assert result.returncode == 0, result.stderr
    assert "scaled" in result.stdout.lower()
    read = k8s_client.read_namespaced_replication_controller(name="r-hp04", namespace="scale-rc-hp04")
    assert read.spec.replicas == 4
