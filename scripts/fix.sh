#!/bin/bash

# Check if a tag is already published in this repo.
function tag_already_published {
    tag_name=$1

    # Check if the name contains "so_ver"
    if echo "$tag_name" | grep -q "so_ver"; then
        return  # Exit the function if "so_ver" is found
    fi

    # get current tags
    current_tags=$(git tag)

    if echo "$tag_name" | grep -q "pkg_ver"; then
        version=${tag_name#*-}  # Correctly extract version from tag_name

        # Match the exact tag (whole word match)
        if echo "$current_tags" | grep -wq "^$version$"; then
            return 0  # Tag already published (success)
        else
            return 1  # No exact match found (failure)
        fi
    else
        # must be a rocm version. If rocm is found in any tag as a local version specifier, 
        # then it has already been published.
        if echo "$current_tags" | grep -q "$tag_name"; then
            return 0 # Tag already published (success)
        else
            return 1 # No match found
        fi
    fi
}

# Generate python wrapper. Change path of rocm library and move files into one directory.
function fix_amdsmi_version {
    # requires amdsmi version
    local version=$1
    cd py-interface

    # Fill in versions
    if compgen -G "*.in" > /dev/null; then
        for file in *.in; do
            sed -i '' "s/@amd_smi_libraries_VERSION_STRING@/$version/g" $file
            mv $file ${file%.in}
        done
    fi

    # Make the wrapper look for `libamd_smi.so` inside `$ROCM_PATH`
    sed -i '' 's/libamd_smi_cwd = Path.cwd()/libamd_smi_cwd = Path(os.environ["ROCM_PATH"]) \/ "lib"/g' amdsmi_wrapper.py

    # Copy over the license file
    cp ../LICENSE . 
    sed -i '' 's/amdsmi\/LICENSE/LICENSE/g' pyproject.toml

    # Prepend notice to the beginning of README.md
    sed -i '' 's/amdsmi\/README.md/README.md/g' pyproject.toml
    (echo -e 'This is an unofficial distribution of the official Python wrapper for amdsmi.\n\nDear AMD: Please contact Jae-Won Chung <jwnchung@umich.edu> to take over the repository when you would like to distribute official bindings under this project name.\n\n'; cat README.md) > README-new.md
    mv README-new.md README.md


    # Create package directory
    mkdir amdsmi
    mv *.py amdsmi

    cd ..
}

# Called when there is a new version of amdsmi.
function clone_and_fix_amdsmi {
    local name=$1
    local commit=$2

    git clone https://github.com/ROCm/amdsmi.git
    cd amdsmi

    # checkout the commit
    git checkout $commit

    local version=""
    local amdsmi_version=""

    # if name begins with "rocm", find amdsmi version
    if echo "$name" | grep -q "rocm"; then
        amdsmi_version=$(grep 'get_package_version_number' CMakeLists.txt | awk -F '"' '{print $2}')
        version="${amdsmi_version}+$name"
    else
        # name looks like "amdsmi_pkg_ver-24.6.0", extract out the version number
        amdsmi_version=${name#*-}
        version=${name#*-}
    fi

    fix_amdsmi_version "$version"

    cd ..

    # move created py-interface into current directory, overwrite previous py-interface
    mv -f ./amdsmi/py-interface ./py-interface

    # remove amdsmi
    rm -rf amdsmi

    # Add and commit py-interface
    git add py-interface
    git commit -m "Add py-interface for version $version"

    # update master
    git push origin master

    git tag "$version"
    git push origin "$version"
}

# AMDSMI Tags
AMDSMI_TAGS_URL="https://api.github.com/repos/ROCm/amdsmi/tags"

# Fetch the JSON data
tags_json=$(curl -s "$AMDSMI_TAGS_URL")

# Check if 'jq' is installed
if ! command -v jq &> /dev/null; then
    echo "'jq' is required but not installed. Please install 'jq' to proceed."
    exit 1
fi

# Extract tag names and commit SHAs into an array
mapfile -t tags_info < <(echo "$tags_json" | jq -c '.[] | {name: .name, sha: .commit.sha}')

# Initialize an array to hold tags with their commit dates
declare -a tags_with_dates

# Process each tag to get the commit date and SHA
for tag in "${tags_info[@]}"; do
    tag_name=$(echo "$tag" | jq -r '.name')
    commit_sha=$(echo "$tag" | jq -r '.sha')

    # Fetch the commit data
    commit_json=$(curl -s "https://api.github.com/repos/ROCm/amdsmi/commits/$commit_sha")
    commit_date=$(echo "$commit_json" | jq -r '.commit.committer.date')

    # Append the data to the array
    tags_with_dates+=("$commit_date $tag_name $commit_sha")
done

# Sort the tags by commit date from oldest to newest
IFS=$'\n' sorted_tags=($(sort <<<"${tags_with_dates[*]}"))
unset IFS

# Loop through the sorted tags
for tag_info in "${sorted_tags[@]}"; do
    # Read the commit date, tag name, and commit SHA
    IFS=' ' read -r commit_date tag_name commit_sha <<< "$tag_info"

    # Call tag_already_published function
    if ! tag_already_published "$tag_name"; then
        echo "New tag detected: $tag_name. Fixing and pushing python wrapper."
        # If tag not already published, call clone_and_fix_amdsmi
        clone_and_fix_amdsmi "$tag_name" "$commit_sha"
    fi
done
