use proconio::input;
fn main (){
let mut _a: i128;
let mut _b: i128;
let mut _c: i128;


input! {
    a: i128,
    b: i128,
    c: i128,

}
 

let x = a + b ;
let y = b + c ;
let z = a + c ;

if x < y && x < z  {
    println!("{}",x);
}else if y < x && y < z {
    println!("{}",y);
}else if z < x && z < y{
    println!("{}",z);

}else {
    println!("{}",x);
}

}
