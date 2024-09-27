# 🐍 Python Bindings for AMDSMI

Community-maintained Python bindings for [AMDSMI](https://github.com/ROCm/amdsmi).

For the source code and API documentation, please see [`py-interface/README.md`](/py-interface).

> [!IMPORTANT]
> At this time, there are no official Python bindings for AMDSMI on PyPI. Rather, bindings are distributed together with ROCm, which complicates dependency management and installation. Thus, we created this community-maintained binding package.
>
> When AMD intends to officially maintain the `amdsmi` package on PyPI, we are happy to transfer ownership. Please contact the current maintainers Parth Raut <praut@umich.edu> and Jae-Won Chung <jwnchung@umich.edu>.

## 🚀 Installation

```
pip install amdsmi
```

Ensure you have the correct ROCm version associated with the version of the amdsmi package, and ROCM_PATH is set correctly. Failure to do so will cause ```import amdsmi``` to fail.

## 📦 Versioning

AMDSMI versions tightly integrated with ROCm versions. Thus, we recommend users to use the AMDSMI Python package version whose version corresponds to their current ROCm version.

Whenever a new release is published to the official `amdsmi` repository, we run a simple script to checkout the `py-interface` directory of the tag and publish it to PyPI.

The versioning of the AMDSMI Python package aligns with the published ROCm version in [AMDSMI Releases](https://github.com/ROCm/amdsmi/releases).
