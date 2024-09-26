# Python Bindings for AMDSMI

Community-maintained Python bindings for [AMDSMI](https://github.com/ROCm/amdsmi).

For the source code and API documentation, please see [`py-interface/README.md`](/py-interface).

> [!IMPORTANT]
> At this time, there are no official Python bindings for AMDSMI on PyPI. Rather, bindings are distributed together with ROCm, which complicates dependency management and installation. Thus, we created this community-maintained binding package.
>
> When AMD intends to officially maintain the `amdsmi` package on PyPI, we are happy to transfer ownership. Please contact the current maintainers Parth Raut <praut@umich.edu> and Jae-Won Chung <jwnchung@umich.edu>.

## Installation

```
pip install amdsmi
```

## Versioning

Whenever a new tag is published to the official `amdsmi` repository, we run a simple script to checkout the `py-interface` directory of the tag and publish it to PyPI.

The versioning of the AMDSMI Python package aligns with both `amdsmi` and ROCm versions to maintain consistency. The `amdsmi` version serves as the primary version, while the ROCm version is appended as a local version specifier (The part after the `+` sign). 

For example:
- When the tag `amdsmi_pkg_ver-24.6.0` is pushed to `ROCm/amdsmi`, the Python package version will be `24.6.0`.
- When the tag `rocm-6.2.1` is pushed to `ROCm/amdsmi`, the Python package version will be `24.6.3+rocm-6.2.1`.

AMDSMI versions tightly integrated with ROCm versions. Thus, we recommend users to use the AMDSMI Python package version whose local version specifier corresponds to their current ROCm version.
