# Build on the Pitaya:
#   cd /opt/redpitaya/www/apps/pitaya_tdc
#   make INSTALL_DIR=/opt/redpitaya

INSTALL_DIR ?= /opt/redpitaya
CXX ?= g++
CFLAGS = -Wall -Wextra -fPIC -O2
LDFLAGS = -shared -fPIC

.PHONY: all clean

all: controllerhf.so
	chmod +x fpga.sh restore_fpga.sh control.sh

controllerhf.so: src/main.cpp
	$(CXX) $(CFLAGS) $(LDFLAGS) -o $@ $<

clean:
	rm -f controllerhf.so src/*.o
