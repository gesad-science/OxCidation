use std::io;

fn main() {
    let mut input = String::new();
    // Read the entire line of input from stdin
    if io::stdin().read_line(&mut input).is_err() { 
        return;
    }

    // Trim potential trailing newline/carriage return characters, mimicking scanf("%s") behavior.
    let str = input.trim();
    
    // Reverse the string by iterating over its characters in reverse order and collecting them into a new String.
    let reversed: String = str.chars().rev().collect();
    
    // Print the final result, which includes the required newline character.
    println!("{}", reversed);
}