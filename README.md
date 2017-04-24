# Fawkes
Fawkes (named after the supermutant companion from Fallout 3) is a mutation testing tool for programs written in C.

## What is Mutation Testing?
Mutation testing is a way of measuring the efficacy of testing by "mutating" the code under test and checking whether the existing testing for that code detects the mutation (assuming that the mutation introduces a bug in previously working code). For more details see [Wikipedia](https://en.wikipedia.org/wiki/Mutation_testing)

## How does Fawkes work?
The user specifies a build command, a single C source file to mutate, and the name of the test executable to run. It is assumed that the test executable will return 0 if the test passes and a non-zero integer otherwise, and that the test passes when no mutations have been performed.

Fawkes performs individual mutations on the target source file, generating a new version of the source for each mutation. The mutated source is substituted for the original source using a hook DLL to intercept calls to syscalls related to file access (such as `open`) and returning the mutated file rather than the original.

## What is Supported?
Fawkes supports C99 (or earlier) code in a Posix environment. There is no windows support at this point.

## What Mutations are performed?
The following lists the current mutations performed by Fawkes:

* Swapping binary operators `+` and `-`
* Swapping binary operators `<<` and `>>`
* Swapping binary operators `!=` and `==`
* Swapping binary operators `&` and `&&`
* Swapping binary operators `&` and `|`
* Swapping binary operators `&&` and `||`
* Swapping binary operators `!=` and `==`
* Swapping binary operators `&` and `&&`
* Swapping binary operators `&` and `|`, and `|=` and `&=`
* Swapping binary operators `&&` and `||`
* Substitutions between any of the following binary operators `<`, `>`, `<=` and `>=`
* Substitutions between any of the pre- or post-fix forms of both the `++` and `--` unary operators, 
* Removing the '!' unary operator
* Removing `break` statements from the body of `case` statements.

## Dependencies
* Fawkes requires Python - either 2 or 3 are supported.
* Fawkes is dependent on the [pycparser](https://github.com/eliben/pycparser) Python module.
* Fawkes is requires the 'diff' command to be present.

## Installation
Fawkes installation is simple:
* Install python (including pip).
* Clone this git repository.
* Use pip to install the python dependencies.

For example:
```
sudo apt-get install python3 python3-pip
git clone https://github.com/juzley/fawkes
cd fawkes
sudo pip install -r requirements.txt
```

It is assumed that if you're writing or testing C code, you probably already have the necessary build tools installed.

## Usage
Usage information can be found by running `fawkes -h` or `fawkes --help`.

As a minimum, the following must be specified:
* The source file to mutate.
* The command to use to build the test.
* The command to use to run the test.

For example:

```fawkes --build_cmd "gcc -o my_test my_code.c my_test.c" --test_exe my_test --src_file my_code.c```
