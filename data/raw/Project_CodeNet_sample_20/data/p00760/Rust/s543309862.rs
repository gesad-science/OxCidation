use std::io;
//use std::collections::HashMap;
//use std::collections::BinaryHeap;
//use std::collections::HashSet;
//use std::mem; // mem::swap(&mut x,&mut y);
//use std::cmp; // cmp::max,cmp::min

#[allow(dead_code)]
fn read_line() -> String{
    let mut s = String::new();
    io::stdin().read_line(&mut s).unwrap();
    s.trim().to_string()
}

#[allow(dead_code)]
fn read_charvec() -> Vec<char>{
    read_line().chars().collect()
}

#[allow(dead_code)]
fn read_ints() -> Vec<i64>{
    let s = read_line();
    let split:Vec<&str> = s.split(" ").collect();
    split.iter().map(|&x| x.to_string().parse().unwrap()).collect()
}

#[allow(dead_code)]
fn read_int() -> i64{
    read_ints()[0]
}

#[allow(dead_code)]
fn reverse(s: &String) -> String{
    s.chars().rev().collect::<String>()
}

#[allow(dead_code)]
fn read_lines(n:i64) -> Vec<String>{
    let mut xs = Vec::new();

    for _i in 0..n{
        xs.push(read_line());
    }

    xs
}

#[allow(dead_code)]
fn read_ints2(n:i64) -> Vec<i64>{
    read_lines(n).iter().map(|x| x.parse().unwrap()).collect()
}

//////////////////////////////////////////////////////////////////////






fn solve()->i64{
    let xs = read_ints();
    let mut y = xs[0];
    let mut m = xs[1];
    let mut d = xs[2];
    let mut s = 0;

    while !(y==1000&&m==1&&d==1){
        let monthday = if m%2 == 1 || y%3==0{
            20
        }else{
            19
        };

        s += monthday - d + 1;
        m += 1;
        d = 1;

        if m == 11 {
            y += 1;
            m=1;
        }
    }

    s
}

fn main(){
    let n = read_int();

    for _i in 0..n{
        println!("{}",solve());
    }

}



/*
DOCS

///////////////// Vec関係 /////////////////

let v = vec![0;2]; // [0,0]
let sum_x = xs.iter().fold(0,|s,i|s+i); // xs : Vec<i64>

s.chars().nth(i as usize).unwrap();

let xs : Vec<i32> = read_charvec().iter().map(|&c| 
    if c == 'A'{
        0
    }else if c == 'B'{
        1
    }else if c == 'X'{
        2
    }else{
        3
    }
).collect();

// 検索
let i = match xs.iter().find(|&&m| m==0){
    Some(v) => true,
    None => false,
};

///////////////// ハッシュマップ /////////////////

let mut h = HashMap::new();
let a = 5;
h.insert(a,true);
match h.get(&a){
    Some(v) => println!("{}",v),
    None    => println!("none"),
}

///////////////// swap /////////////////

let mut x = 5;
let mut y = 1;
mem::swap(&mut x,&mut y);

///////////////// priority queue /////////////////

// https://doc.rust-lang.org/std/collections/struct.BinaryHeap.html
let mut heap = BinaryHeap::new();

heap.push(1);
heap.push(5);
heap.push(2);

assert_eq!(heap.pop(), Some(5));
assert_eq!(heap.pop(), Some(2));
assert_eq!(heap.pop(), Some(1));
assert_eq!(heap.pop(), None);

let mut vs = heap.into_vec();
vs.reverse();

*/

