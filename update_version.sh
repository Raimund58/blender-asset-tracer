#!/bin/bash

if [ -z "$1" ]; then
    echo "Usage: $0 new-version" >&2
    exit 1
fi

uv version $1
sed "s/__version__\s*=\s*\"[^']*\"/__version__ = \"$1\"/" -i src/blender_asset_tracer/__init__.py
sed --posix "s/\(dist\/blender[_-]asset[_-]tracer-\)\([0-9.betalphdv-]*[0-9]\)/\1$1/g" -i README.md

git diff
echo
echo "Don't forget to commit and tag:"
echo git commit -m \'Bumped version to $1\' pyproject.toml uv.lock src/blender_asset_tracer/__init__.py README.md
echo git tag -a v$1 -m \'Tagged version $1\'
echo
echo "Build the package & upload to PyPi using:"
echo "uv build"
echo "uv sync --group release"
echo "uv run twine check dist/blender_asset_tracer-$1.tar.gz dist/blender_asset_tracer-$1-*.whl"
echo "uv run twine upload -r bat dist/blender_asset_tracer-$1.tar.gz dist/blender_asset_tracer-$1-*.whl"
