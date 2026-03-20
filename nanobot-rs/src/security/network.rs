use std::net::IpAddr;

use regex::Regex;
use url::Url;

pub fn contains_internal_url(input: &str) -> bool {
    let regex = Regex::new(r#"https?://[^\s"')>]+"#).expect("valid url regex");
    regex.find_iter(input).any(|mat| {
        validate_url_target(mat.as_str())
            .map(|allowed| !allowed)
            .unwrap_or(false)
    })
}

pub fn validate_url_target(raw: &str) -> anyhow::Result<bool> {
    let url = Url::parse(raw)?;
    let Some(host) = url.host_str() else {
        return Ok(true);
    };
    if host.eq_ignore_ascii_case("localhost") {
        return Ok(false);
    }
    if let Ok(ip) = host.parse::<IpAddr>() {
        return Ok(!is_private_ip(ip));
    }
    Ok(true)
}

fn is_private_ip(ip: IpAddr) -> bool {
    match ip {
        IpAddr::V4(v4) => {
            v4.is_private() || v4.is_loopback() || v4.is_link_local() || v4.is_broadcast()
        }
        IpAddr::V6(v6) => v6.is_loopback() || v6.is_unspecified() || v6.is_unique_local(),
    }
}
