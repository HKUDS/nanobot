//! One live window stream. The native system Stop Sharing callback revokes
//! the SDK session, not just the visual indicator. No audio or recording.
use std::sync::{atomic::{AtomicBool, AtomicUsize, Ordering}, Arc};
use std::time::{Duration, Instant};

use anyhow::{ensure, Result};
use cua_driver_sdk::CuaDriverSession;
use screencapturekit::prelude::*;
use screencapturekit::stream::delegate_trait::StreamCallbacks;

use crate::{policy::Target, Revocation};

pub struct Sharing {
    stream: SCStream,
    intentional: Arc<AtomicBool>,
    pub target: Target,
}

impl Sharing {
    pub fn start(target: Target, session: Arc<CuaDriverSession>, revocation: Arc<Revocation>) -> Result<Self> {
        let content = SCShareableContent::get()?;
        let window = content.windows().into_iter().find(|w| w.window_id() == target.window)
            .ok_or_else(|| anyhow::anyhow!("The selected window is no longer available."))?;
        ensure!(window.owning_application().is_some_and(|app| app.process_id() == target.pid), "The selected window belongs to a different process. Refresh list_windows.");
        let filter = SCContentFilter::create().with_window(&window).build();
        let bounds = filter.content_rect();
        ensure!(bounds.size.width.is_finite() && bounds.size.height.is_finite()
            && bounds.size.width > 0.0 && bounds.size.height > 0.0, "The window has no capturable surface.");
        // The stream exists for native sharing/lifecycle. Model screenshots
        // remain the SDK's exact window captures, never these preview frames.
        let scale = (640.0 / bounds.size.width).min(1.0);
        let config = SCStreamConfiguration::new()
            .with_width((bounds.size.width * scale).round().max(1.0) as u32)
            .with_height((bounds.size.height * scale).round().clamp(1.0, 4096.0) as u32)
            .with_minimum_frame_interval(&CMTime::new(1, 2))
            .with_shows_cursor(false).with_captures_audio(false);
        let intentional = Arc::new(AtomicBool::new(false));
        let stop = {
            let intentional = intentional.clone();
            let revocation = revocation.clone();
            let session = session.clone();
            move || {
                if !intentional.load(Ordering::Acquire) {
                    revocation.revoke();
                    session.close();
                }
            }
        };
        let on_error = stop.clone();
        let on_inactive = stop.clone();
        let callbacks = StreamCallbacks::new()
            .on_stop(move |_| stop())
            .on_error(move |_| on_error())
            .on_inactive(on_inactive);
        let frames = Arc::new(AtomicUsize::new(0));
        let output_frames = frames.clone();
        let mut stream = SCStream::new_with_delegate(&filter, &config, callbacks);
        stream.add_output_handler(move |sample: CMSampleBuffer, _| {
            if sample.image_buffer().is_some() { output_frames.fetch_add(1, Ordering::Release); }
        }, SCStreamOutputType::Screen).ok_or_else(|| anyhow::anyhow!("Could not attach the native sharing stream."))?;
        let sharing = Self { stream, intentional, target };
        sharing.stream.start_capture()?;
        let start = Instant::now();
        while frames.load(Ordering::Acquire) == 0 {
            ensure!(!revocation.paused.load(Ordering::Acquire), "Sharing was stopped.");
            ensure!(start.elapsed() < Duration::from_secs(8), "No frame received from the selected window. Check Screen Recording permission.");
            std::thread::sleep(Duration::from_millis(30));
        }
        Ok(sharing)
    }
}

impl Drop for Sharing {
    fn drop(&mut self) {
        self.intentional.store(true, Ordering::Release);
        let _ = self.stream.stop_capture();
    }
}
