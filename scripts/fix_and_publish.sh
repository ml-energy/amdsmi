#!/usr/bin bash

set -ev

function tag_already_published {
    tag_name=$1

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

function clone_and_fix_amdsmi {
    local name=$1
    local commit=$2

    # TODO: clone amdsmi -b with commit so you don't need to check out
    # fetch depths = make it 0 or 1 
    git clone https://github.com/ROCm/amdsmi.git
    cd amdsmi

    # checkout the commit
    git checkout $commit

    # initialize version variable
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

    # move created py-interface into current directory
    mv ./amdsmi/py-interface ./py-interface

    # remove amdsmi
    rm -rf amdsmi

    # Add and commit py-interface
    git add py-interface
    git commit -m "Add py-interface for version $version"

    git tag "$version"
    git push origin "$version"

    # remove the py-interface directory
    rm -rf py-interface
}



function clone_and_publish_tags {
    name=$1
    commit=$2

    # Check if the name contains "so_ver"
    if echo "$name" | grep -q "so_ver"; then
        return  # Exit the function if "so_ver" is found
    fi

    if tag_already_published "$name"; then
        echo "$name already published, skipping."
        return # Exit if tag already published
    fi

    # Clone, copy, fix, and push tag
    clone_and_fix_amdsmi "$name" "$commit"
}

API_URL="https://api.github.com/repos/ROCm/amdsmi/tags"

api_output=$(curl -s $API_URL)

echo "$api_output" | jq -c '.[]' | while IFS= read -r item; do
  # Extract the name and commit URL using jq
  name=$(echo "$item" | jq -r '.name')
  commit_url=$(echo "$item" | jq -r '.commit.url')
  commit_id=${commit_url##*/}

  echo "Processing $name with commit $commit_id"

  # Call function that takes in name and commit id
  clone_and_publish_tags "$name" "$commit_id"

done