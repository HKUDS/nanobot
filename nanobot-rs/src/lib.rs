pub mod agent;
pub mod bus;
pub mod channels;
pub mod cli;
pub mod config;
pub mod providers;
pub mod security;
pub mod session;
pub mod tools;

pub fn init_tracing() {
    let _ = tracing_subscriber::fmt()
        .with_env_filter(
            tracing_subscriber::EnvFilter::try_from_default_env()
                .unwrap_or_else(|_| tracing_subscriber::EnvFilter::new("info")),
        )
        .try_init();
}
