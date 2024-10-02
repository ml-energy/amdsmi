#!/bin/bash

set -ev

# Check if a tag is already published in this repo.
function tag_already_published {
    version_number=$1

    # get current tags
    current_tags=$(git tag)

    if echo "$current_tags" | grep -q "$version_number"; then
        return 0 # Tag already published (success)
    else
        return 1 # No match found
    fi
}

# Generate python wrapper. Change path of rocm library and move files into one directory.
function fix_amdsmi_version {

    local version=$1
    cd py-interface

    # Fill in versions
    if compgen -G "*.in" > /dev/null; then
        for file in *.in; do
            sed -i "s/@amd_smi_libraries_VERSION_STRING@/$version/g" $file
            mv $file ${file%.in}
        done
    fi

    # Make the wrapper look for `libamd_smi.so` inside `$ROCM_PATH`
    sed -i 's/libamd_smi_cwd = Path.cwd()/libamd_smi_cwd = Path(os.environ["ROCM_PATH"]) \/ "lib"/g' amdsmi_wrapper.py

    # Copy over the license file
    cp ../LICENSE . 
    sed -i 's/amdsmi\/LICENSE/LICENSE/g' pyproject.toml

    # Prepend notice to the beginning of README.md
    sed -i 's/amdsmi\/README.md/README.md/g' pyproject.toml
    (echo -e 'This is an unofficial distribution of the official Python wrapper for amdsmi. See https://github.com/ml-energy/amdsmi for distribution scripts and source code.\n\nAMD -- Please contact Parth Raut (<praut@umich.edu>) and Jae-Won Chung (<jwnchung@umich.edu>) to take over the repository when you would like to distribute official bindings under this project name.\n\n'; cat README.md) > README-new.md
    mv README-new.md README.md


    # Create package directory
    mkdir amdsmi
    mv *.py amdsmi

    cd ..
}

# Called when there is a new version of amdsmi.
function clone_and_fix_amdsmi {
    local commit=$1
    local version=$2

    git clone https://github.com/ROCm/amdsmi.git
    cd amdsmi

    # checkout the commit
    git checkout $commit

    fix_amdsmi_version "$version"

    cd ..

    # move created py-interface into current directory, overwrite previous py-interface
    rm -rf ./py-interface
    mv -f ./amdsmi/py-interface ./py-interface

    # remove amdsmi
    rm -rf amdsmi

    # Add and commit py-interface
    git add py-interface
    git commit -m "Add py-interface for version $version"

    # update master
    git push origin master

    sleep 1 # avoid race condition where github doesn't recognize new tag on push

    git tag "$version"
    git push origin "$version"
}

# AMDSMI Latest Release
AMDSMI_RELEASE_URL="https://api.github.com/repos/ROCm/amdsmi/releases/latest"

# Check if 'jq' is installed
if ! command -v jq &> /dev/null; then
    echo "'jq' is required but not installed. Please install 'jq' to proceed."
    exit 1
fi

# Associated tag with release (ex. rocm-6.2.1)
tag_name=$(curl -s $AMDSMI_RELEASE_URL | jq -r '.tag_name')

# Extract out the version number (ex. 6.2.1)
version_number=$(echo "$tag_name" | sed 's/^rocm-//')

# Call tag_already_published function to check if tag has been published.
if ! tag_already_published "$version_number"; then
    echo "New tag detected: $tag_name. Building and pushing python wrapper."

    # retrive commit_sha from Github tags API
    commit_hash=$(curl -s https://api.github.com/repos/ROCm/amdsmi/git/ref/tags/$tag_name | jq -r '.object.sha')

    # If tag not already published, call clone_and_fix_amdsmi
    clone_and_fix_amdsmi "$commit_hash" "$version_number"
fi
