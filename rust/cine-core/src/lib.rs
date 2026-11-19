//! A dependency-free, streaming Phantom CINE reader and writer.
//!
//! The Rust API works without Python or MATLAB. See [`Reader`].
use std::fmt;

pub mod lookup;
pub mod reader;
pub use reader::{decode, FrameInfo, Info, Metadata, Reader};

#[derive(Debug)]
pub enum Error {
    Io(std::io::Error),
    Format(String),
}
impl Error {
    pub fn format(message: impl Into<String>) -> Self {
        Self::Format(message.into())
    }
}
impl From<std::io::Error> for Error {
    fn from(e: std::io::Error) -> Self {
        Self::Io(e)
    }
}
impl fmt::Display for Error {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::Io(e) => e.fmt(f),
            Self::Format(s) => s.fmt(f),
        }
    }
}
impl std::error::Error for Error {}
pub type Result<T> = std::result::Result<T, Error>;
