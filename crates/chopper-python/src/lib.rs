use chopper::job::{Error, ExecutionControl as Control, Job as RustJob};
use pyo3::{create_exception, exceptions::PyException, prelude::*};
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

#[pymodule]
fn _native(module: &Bound<'_, PyModule>) -> PyResult<()> {
    module.add("ChopperError", module.py().get_type::<ChopperError>())?;
    module.add_class::<ExecutionControl>()?;
    module.add_class::<NativeJob>()
}
