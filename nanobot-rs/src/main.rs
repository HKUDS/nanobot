use anyhow::Result;

#[tokio::main]
async fn main() -> Result<()> {
    nanobot_rs::init_tracing();
    nanobot_rs::cli::run().await
}
