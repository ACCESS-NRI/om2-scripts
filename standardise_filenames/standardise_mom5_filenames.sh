#!/usr/bin/bash
# Copyright 2024 ACCESS-NRI and contributors. See the top-level COPYRIGHT file for details.
# SPDX-License-Identifier: Apache-2.0.
#
# Standardise file naming for MOM5 output files in access-om2 by removing the underscore before the four-digit year, i.e., replacing '_YYYY' with 'YYYY'
# This was written assuming it would be used as a payu "userscript" at the "archive" stage, but alternatively a path to an "archive" directory can be provided.
# For more details, see https://github.com/COSIMA/om3-scripts/issues/32

Help()
{
    # Display help
    echo -e "Standardise file naming for MOM5 output files.\n"
    echo "Syntax: $(basename "$0") [-h|-d DIRECTORY]"
    echo "options:"
    echo "h    Print this help message."
    echo -e "d    Process files in the specified 'DIRECTORY'."
}

while getopts ":hd:" option; do
    case $option in
        h) # display help
           Help
           exit;;
        d) # Enter a directory
            out_dir=$OPTARG
            if [ ! -d "$out_dir" ]; then
                echo "Error: $out_dir Does not exist" >&2
                exit 1
            fi;;
        \?) # Invalid option
            echo "Error: Invalid option" >&2
            exit 1;;
    esac
done

# if no directory was specified, collect all directories from 'archive'
if [ -z "$out_dir" ]; then
    out_dirs=(archive/output*[0-9]/ocean)
else
    out_dirs=("$out_dir")
fi

# process each output directory
for dir in "${out_dirs[@]}"; do
    # process each mom5 file
    for current_file in "$dir"/access-om2.mom5.*.nc*; do
       if [ -f "$current_file" ]; then
            base=$(basename "$current_file")
            new_base=$(echo "$base" | sed -E 's/_([0-9]{4})([-.])/\1\2/')
            new_filename=$dir/$new_base
            # rename the file without overwriting existing files
            mv -n "$current_file" "$new_filename"
        fi
    done
done

