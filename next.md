manual testing:

smoke that the `mng create` is not broken:

mng create docker1@foo.docker --new-host
mng create docker2@foo.docker

test address support on a non-destroy command:

mng stop docker2
mng stop docker1@foo.docker

test address support on destroy:

mng destroy docker1@foo.docker
mng destroy docker2
