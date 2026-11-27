use chopper::job::{
    Error, ExecutionControl as Control, Job as RustJob, ManifestReader as RustManifestReader,
};
use pyo3::{
    create_exception,
    exceptions::{PyException, PyValueError},
    prelude::*,
};
use serde::Serialize;
use std::path::PathBuf;

create_exception!(chopper_csv, ChopperError, PyException);

fn job_error(py: Python<'_>, error: Error) -> PyErr {
    let result = ChopperError::new_err(error.to_string());
    let value = result.value(py);
    value
        .setattr("code", error.code())
        .and_then(|()| value.setattr("path", error.path()))
        .and_then(|()| value.setattr("line", error.line()))
        .and_then(|()| value.setattr("column", error.column()))
        .err()
        .unwrap_or(result)
}

fn dictionary<'py>(py: Python<'py>, report: &impl Serialize) -> PyResult<Bound<'py, PyAny>> {
    let json = serde_json::to_string(report)
        .map_err(|error| pyo3::exceptions::PyRuntimeError::new_err(error.to_string()))?;
    py.import("json")?.call_method1("loads", (json,))
}

#[pyclass(frozen, module = "chopper_csv")]
#[derive(Default)]
/// Cancellation and progress for one Analyze or Run call.
struct ExecutionControl {
    inner: Control,
}

#[pymethods]
impl ExecutionControl {
    #[new]
    fn new() -> Self {
        Self::default()
    }

    /// Request cancellation of the execution.
    fn cancel(&self) {
        self.inner.cancel();
    }

    /// Return a snapshot of the latest execution progress.
    fn progress<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyAny>> {
        dictionary(py, &self.inner.progress())
    }
}

#[pyclass(frozen)]
struct NativeJob {
    inner: RustJob,
}

#[pymethods]
impl NativeJob {
    #[staticmethod]
    fn from_json(py: Python<'_>, source: &str) -> PyResult<Self> {
        RustJob::from_json(source)
            .map(|inner| Self { inner })
            .map_err(|error| job_error(py, error))
    }

    #[staticmethod]
    fn load(py: Python<'_>, path: PathBuf) -> PyResult<Self> {
        RustJob::load(path)
            .map(|inner| Self { inner })
            .map_err(|error| job_error(py, error))
    }

    fn save(&self, py: Python<'_>, path: PathBuf) -> PyResult<()> {
        self.inner.save(path).map_err(|error| job_error(py, error))
    }

    fn to_dict<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyAny>> {
        dictionary(py, self.inner.settings())
    }

    fn validate(&self, py: Python<'_>) -> PyResult<()> {
        self.inner.validate().map_err(|error| job_error(py, error))
    }

    fn inspect<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyAny>> {
        let report = py
            .detach(|| self.inner.inspect())
            .map_err(|error| job_error(py, error))?;
        dictionary(py, &report)
    }

    fn preview<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyAny>> {
        let report = py
            .detach(|| self.inner.preview())
            .map_err(|error| job_error(py, error))?;
        dictionary(py, &report)
    }

    fn detect_dialect<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyAny>> {
        let report = py
            .detach(|| self.inner.detect_dialect())
            .map_err(|error| job_error(py, error))?;
        dictionary(py, &report)
    }

    fn analyze<'py>(
        &self,
        py: Python<'py>,
        control: Option<&ExecutionControl>,
    ) -> PyResult<Bound<'py, PyAny>> {
        let control = control.map(|control| &control.inner);
        let report = py
            .detach(|| self.inner.analyze(control))
            .map_err(|error| job_error(py, error))?;
        dictionary(py, &report)
    }

    fn run<'py>(
        &self,
        py: Python<'py>,
        control: Option<&ExecutionControl>,
    ) -> PyResult<Bound<'py, PyAny>> {
        let control = control.map(|control| &control.inner);
        let report = py
            .detach(|| self.inner.run(control))
            .map_err(|error| job_error(py, error))?;
        dictionary(py, &report)
    }
}

#[pyfunction]
/// Return the built-in calculated-column functions as name and signature pairs.
fn formula_functions() -> Vec<(&'static str, &'static str)> {
    chopper::job::formula_functions().to_vec()
}

#[pyfunction]
fn _validate_formula(source: &str) -> PyResult<()> {
    chopper::formula::parse(source)
        .map(|_| ())
        .map_err(|error| PyValueError::new_err(error.to_string()))
}

#[pyclass(name = "ManifestReader", module = "chopper_csv")]
/// Stream metadata from one published native result manifest.
struct ManifestReader {
    inner: RustManifestReader,
}

#[pymethods]
impl ManifestReader {
    #[getter]
    fn header<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyAny>> {
        dictionary(py, self.inner.header())
    }

    fn __iter__(slf: PyRef<'_, Self>) -> PyRef<'_, Self> {
        slf
    }

    fn __next__<'py>(&mut self, py: Python<'py>) -> PyResult<Option<Bound<'py, PyAny>>> {
        let output = py
            .detach(|| self.inner.next())
            .transpose()
            .map_err(|error| job_error(py, error))?;
        output.map(|entry| dictionary(py, &entry)).transpose()
    }

    fn __enter__(slf: PyRef<'_, Self>) -> PyRef<'_, Self> {
        slf
    }

    fn __exit__(
        &mut self,
        _kind: &Bound<'_, PyAny>,
        _value: &Bound<'_, PyAny>,
        _traceback: &Bound<'_, PyAny>,
    ) {
        self.close();
    }

    /// Close the manifest early.
    fn close(&mut self) {
        self.inner.close();
    }
}

const DEFAULT_MANIFEST_RECORD_BYTES: usize = 16 * 1024 * 1024;

#[pyfunction(signature = (path, *, max_record_bytes = DEFAULT_MANIFEST_RECORD_BYTES))]
/// Open a native result manifest with a limit on each JSON Lines record.
fn open_manifest(
    py: Python<'_>,
    path: PathBuf,
    max_record_bytes: usize,
) -> PyResult<ManifestReader> {
    py.detach(|| RustManifestReader::open(path, max_record_bytes))
        .map(|inner| ManifestReader { inner })
        .map_err(|error| job_error(py, error))
}

#[pymodule]
fn _native(module: &Bound<'_, PyModule>) -> PyResult<()> {
    module.add("ChopperError", module.py().get_type::<ChopperError>())?;
    module.add_class::<ExecutionControl>()?;
    module.add_class::<ManifestReader>()?;
    module.add_function(wrap_pyfunction!(formula_functions, module)?)?;
    module.add_function(wrap_pyfunction!(open_manifest, module)?)?;
    module.add_function(wrap_pyfunction!(_validate_formula, module)?)?;
    module.add_class::<NativeJob>()
}
