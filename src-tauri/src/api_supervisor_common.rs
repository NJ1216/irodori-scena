//! Token generation and health-body check shared by the macOS and Windows supervisors.
use std::io;

/// Returns a fresh 256-bit random token as lowercase hex.
pub fn generate_token() -> io::Result<String> {
    let mut bytes = [0_u8; 32];
    getrandom::fill(&mut bytes).map_err(|error| io::Error::other(error.to_string()))?;
    Ok(bytes.iter().map(|byte| format!("{byte:02x}")).collect())
}

/// True when a raw HTTP response is a 200 whose body reports `"ok":true`.
pub fn health_response_ok(response: &str) -> bool {
    response.starts_with("HTTP/1.1 200") && response.contains("\"ok\":true")
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn tokens_are_64_hex_characters_and_differ() {
        let first = generate_token().unwrap();
        assert_eq!(first.len(), 64);
        assert!(first.bytes().all(|b| b.is_ascii_hexdigit()));
        assert_ne!(first, generate_token().unwrap());
    }

    #[test]
    fn health_requires_status_200_and_ok_true_body() {
        assert!(health_response_ok(
            "HTTP/1.1 200 OK\r\ncontent-type: application/json\r\n\r\n{\"ok\":true}"
        ));
        assert!(!health_response_ok("HTTP/1.1 200 OK\r\n\r\n{\"ok\":false}"));
        assert!(!health_response_ok("HTTP/1.1 200 OK\r\n\r\n"));
        assert!(!health_response_ok(
            "HTTP/1.1 500 Error\r\n\r\n{\"ok\":true}"
        ));
    }
}
