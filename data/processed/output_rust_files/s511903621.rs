use std::io::{self, Write, Read}; // Import io for standard input/output operations and Read trait

fn main() -> io::Result<()> {
    // Read all bytes from stdin until EOF
    let mut buffer = Vec::new();
    io::stdin().read_to_end(&mut buffer)?;

    // Process each byte as a character and print its uppercase version.
    for &byte in buffer.iter() {
        // Convert the byte to a char (assuming valid UTF-8 or single ASCII bytes)
        let c = char::from(byte);
        
        // Apply the uppercase transformation, matching C's toupper behavior for basic characters.
        let upper_c = c.to_ascii_uppercase();
        
        // Print the character without a newline separator (matching printf("%c", ...))
        print!("{}", upper_c);
    }

    // Ensure all buffered output is written before exiting.
    io::stdout().flush()?;
    Ok(())
}