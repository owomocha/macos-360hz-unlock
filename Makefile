CFLAGS ?= -O2 -Wall
FRAMEWORKS = -framework IOKit -framework CoreFoundation -framework CoreGraphics

vedid: vedid.c
	clang $(CFLAGS) -o $@ $< $(FRAMEWORKS)

test:
	python3 -m unittest discover -s tests -v

clean:
	rm -f vedid

.PHONY: test clean
