# Out-of-tree build of hp-wmi with the board-8746 quirk (see patch-8746.py).
# Built as hp-wmi.ko so DKMS can install it to updates/, where it takes
# precedence over the in-tree module of the same name.

obj-m += hp-wmi.o

KVER ?= $(shell uname -r)
KDIR ?= /lib/modules/$(KVER)/build

all:
	$(MAKE) -C $(KDIR) M=$(CURDIR) modules

clean:
	$(MAKE) -C $(KDIR) M=$(CURDIR) clean
