"""Compiling Fortran code."""

import contextlib
import datetime
import io
import logging
import os
import pathlib
import subprocess
import typing as t

import argunparse
import numpy.f2py

from ..general import Compiler


_LOG = logging.getLogger(__name__)


def create_f2py_module_name(path: pathlib.Path) -> str:
    return '{}_transpyle_{}'.format(path.stem, datetime.datetime.now().strftime('%Y%m%d%H%M%S'))


class F2PyCompiler(Compiler):

    """Compile Fortran code into Python extension modules using f2py."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.argunparser = argunparse.ArgumentUnparser()

    def run_f2py(
            self, code: str, path: pathlib.Path, module_name: str,
            *args, **kwargs) -> subprocess.CompletedProcess:
        """Run f2py with given arguments."""
        assert isinstance(code, str), type(code)
        assert isinstance(path, pathlib.Path), type(path)
        assert isinstance(module_name, str), type(module_name)
        extra_args = self.argunparser.unparse(*args, **kwargs)
        stdout = io.StringIO()
        stderr = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            with contextlib.redirect_stderr(stderr):
                returncode = numpy.f2py.compile(
                    source=code, modulename=module_name, extra_args=extra_args,
                    verbose=False, source_fn=str(path), extension=path.suffix)
        result = subprocess.CompletedProcess(
            args='f2py -c -m {} {} {}'.format(module_name, extra_args, str(path)),
            returncode=returncode, stdout=stdout.getvalue(), stderr=stderr.getvalue())
        return result

    def compile(self, code: str, path: t.Optional[pathlib.Path] = None,
                output_path: t.Optional[pathlib.Path] = None, *args, **kwargs) -> pathlib.Path:
        assert isinstance(code, str), type(code)
        assert isinstance(path, pathlib.Path), type(path)
        assert path.is_file(), path
        assert isinstance(output_path, pathlib.Path), type(output_path)
        assert output_path.is_dir(), output_path

        module_name = create_f2py_module_name(path)
        # if __debug__:
        _LOG.debug('f2py compiling file: "%s", (%i characters)', path, len(code))
        # _LOG.debug('compiled file\'s contents: %s', code)

        # module_name = cls.create_module_name(code, file_name)
        # if __debug__:
        _LOG.debug('f2py desired module name: %s', module_name)

        # if 'debug' in extra_args or 'debug-capi' in extra_args:
        #    _LOG.warning('building f2py module in debug mode')

        # args = (*args, '-v')
        # kwargs['f90exec'] = 'gfortran'
        # kwargs['f77flags'] = '-g0'
        # kwargs['f90exec'] = 'gfortran'
        # kwargs['f90flags'] = '-g0'
        kwargs['opt'] = '-O3 -funroll-loops'
        # kwargs['noopt'] = True

        _working_dir = pathlib.Path.cwd()
        os.chdir(str(output_path))
        result = self.run_f2py(code, path, module_name, *args, **kwargs)
        os.chdir(str(_working_dir))

        # if __debug__:
        # if result.returncode == 0:
        _LOG.debug('f2py result: %s', result)
        # else:
        #    _LOG.error(F2PY_ERROR_REPORT_FMT, result.returncode, result.stdout, result.stderr)

        if result.returncode != 0:
            raise RuntimeError(
                '{} returned a non-zero status: {}\nstdout="""{}"""\nstderr={}'
                .format(result.args, result.returncode, result.stdout, result.stderr))
        # print(result.args)
        # print(result.returncode)
        # print(result.stdout)
        # print(result.stderr)

        results = [result for result in output_path.glob('{}*'.format(module_name))
                   if result.is_file()]
        assert len(results) == 1, results
        return results[0]