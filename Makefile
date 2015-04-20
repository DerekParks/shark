INSTALL_DIR=/usr/local/bin

CC=gcc
RM=rm
CP=cp

CFLAGS += `pkg-config libhid --cflags` -pedantic
LIBS += `pkg-config libhid --libs`

all: shark

shark:
	${CC} ${CFLAGS} -o shark shark.c ${LIBS}

clean:
	${RM} -f shark

install: shark
	${CP} -f shark ${INSTALL_DIR}/shark

uninstall:
	${RM} -f ${INSTALL_DIR}/shark
