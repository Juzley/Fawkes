.PHONY: default all clean
all: default
default:
	cc -fPIC -shared -o inject.so inject.c -ldl
clean:
	-rm -f *.o inject.so
