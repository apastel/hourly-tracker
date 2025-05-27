#!/bin/bash

shopt -s nullglob  # Allow loops over empty directories (optional)

for file in src/main/resources/*.ui; do
  output_file="src/main/python/generated/ui_$(basename "${file/.ui}").py"
  pyside6-uic -o "$output_file" "$file"
done
