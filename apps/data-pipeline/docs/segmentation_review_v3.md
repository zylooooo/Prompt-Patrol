# Segmenter validation, fifty answers

For each answer: OK if every sentence boundary is right, otherwise WRONG plus a note.

## E12.Q10.A13

1. If the binary search tree is constructed efficiently, best case scenario is O(log n) time.
2. Where n is the number of items in the tree.
3. If the binary search tree is constructed poorly, with for instance the root of the tree being 1, and progressing downwards and to the right its children are each more than the last: you have a one-way linear linked list.
4. That worse case scenario would be a full traversal at O(n) time.
5. Where n is the number of items in the tree.

verdict: OK

## E01.Q06.A28

1. It depends if it’s a global then they have to be declared out side the source code to be used in every scope however a local variable is one declared in a local function etc. which obviously doesn’t need to be declared outside the variable seeing how it is used for the function or block its being called for.

verdict: OK

## E08.Q05.A08

1. The list-based implementation is preferred since the big O(1) is very efficient.

verdict: OK

## E01.Q01.A18

1. It tests the main function of the program while leaving out the finer details.

verdict: OK

## E12.Q07.A20

1. push, which adds an item to the top of the stack, and pop, which takes the first item off the top to the stack

verdict: OK

## E01.Q06.A24

1. global variables are declared in the main function
2. local variables are declared in any other function

verdict: OK

## E03.Q01.A15

1. A function signature includes the name of the function and types of arguments, but not the return type.

verdict: OK

## E12.Q10.A12

1. O( Log (n) )

verdict: OK

## E04.Q01.A06

1. 1. Declare the length of the array (int array[10];)
2. 2. Initialize the array (int array
3. [] = {0, 1, 2, 3}; //compiler will assume size of 4)

verdict: WRONG, split inside code fragment

## E08.Q01.A15

1. Stores a set of elements in a particular order
2. based on the principle of Last In First Out (LIFO).

verdict: WRONG, split at mid-sentence wrap

## E08.Q06.A14

1. i have an hard time explaining this so i'll show how infix is evaluated instead.
2. Start with an infix expression, like, (((5+2)*5)+(400/(2+3))), and  push items until you get a ")" and once that happens, perform the operations until you reach an "("... with that complete, you will now have
3. ((7*5)+(400/(2+3)))
4. as now the expression that will be evaluated... perform last step again...
5. (35+(400/(2+3))) is now the stack....
6. repeat agian...
7. (35+(400/5)) is now the stack after that.... repeat...
8. (35+80) is now the stack, repeat again...
9. 115 is now the stack, and is returned.

verdict: WRONG, pathological: wraps, code splits, inconsistent ellipses

## E03.Q06.A18

1. There is no base case.
2. The recursion step doesn't reduce the problem during each recursive call.

verdict: OK

## E11.Q01.A22

1. class name
2. data of class
3. definition of functions and methods

verdict: OK

## E03.Q06.A26

1. no base case or if the programmar does not define the base case as the simplest case and it never gets reached

verdict: OK

## E01.Q03.A18

1. Encapsulation - Objects use operations without knowing how the operation works.
2. Inheritance - cuts redundancy by reusing earlier classes.
3. Polymorphism - objects select the correct operation to use in the situation.

verdict: OK

## E03.Q07.A18

1. Both involve a termination test.
2. They use a control statement and repition to solve the problem.
3. They can also result in an infinite loop.

verdict: OK

## E12.Q03.A06

1. log(logn)
2. 2^(logn)
3. n!
4. n^3
5. n^2

verdict: OK

## E03.Q06.A15

1. If the recursion function never reaches or successfully defines the base case it will recurse forever.
2. This happens many ways, such as the function doesn't progress towards the base case, or the function is coded poorly and doesn't even contain a base case.

verdict: OK

## E12.Q05.A27

1. linked list many be dynamically grown.
2. It has not limit

verdict: OK

## E01.Q03.A02

1. The main advantages to object-oriented programming are that existing classes can be reused and program maintenance and verification are easier.

verdict: OK

## E01.Q06.A17

1. In the declaration of Functions, for statements, and while statements.
2. in the body of If, For, while, do while, statements, in namespaces, headers, etc  ( almost anywhere. )
3. anywhere in the program, as long as it is on it's own line.

verdict: OK

## E05.Q03.A18

1. worst case its = O(n) time
2. best case its = O(n^2) time

verdict: OK

## E02.Q02.A21

1. Local variables cannot be used outside of that function body.
2. When a function terminates the values of its local variables are lost.
3. Where as data members are variables in a class definition, and they exist throughout the life of the object.

verdict: OK

## E02.Q06.A00

1. A function definition does not require any additional information that needs to be passed inside its parenthesis
2. to execute.
3. While a definition prototype requires more than one parameters to be passed in order to complete its task.

verdict: WRONG, split at mid-sentence wrap

## E09.Q07.A15

1. Queue

verdict: OK

## E10.Q05.A18

1. A binary search tree is a special binary tree arranged such that every left child node contains a value less than its parent, and every right child node contains a value greater its parent.

verdict: OK

## E05.Q04.A07

1. Best case is one element.
2. One element is sorted.

verdict: OK

## E11.Q02.A11

1. public and private.

verdict: OK

## E10.Q04.A06

1. a tree with up to two children or a right subtree and/or a left subtree

verdict: OK

## E03.Q07.A08

1. Both are repetative and both have a end test.

verdict: OK

## E10.Q03.A03

1. A tree node with no children.

verdict: OK

## E02.Q03.A12

1. A constructor initialized values at the execution of its instantiation.
2. It provides default values.

verdict: OK

## E11.Q07.A02

1. Arrays declared as static are not created and initialized when a function is called and destroyed when the function terminates.

verdict: OK

## E03.Q05.A14

1. Overloaded functions are differentiated by their parameters.

verdict: OK

## E08.Q03.A16

1. with the element added to the array, so that the last element added is at the end, and when the element is popped it takes the last element off the array

verdict: OK

## E02.Q06.A10

1. Function definitions are just that, the definition.
2. The prototype is what the compiler uses to check that calls to function are correct.

verdict: OK

## E10.Q06.A04

1. (Left side of tree)
2. (Root) (Right side of tree)

verdict: WRONG, list or fragment answer, not prose

## E10.Q03.A04

1. And end point of the tree... a node that does not have any children.

verdict: OK

## E02.Q01.A01

1. The attributes of said class.
2. Also whether or not it is a subclass.
3. Also whether it is public private or protected.

verdict: OK

## E03.Q02.A21

1. The entire program.

verdict: OK

## E03.Q07.A07

1. anything you can do iterativly you can do recursively

verdict: OK

## E11.Q04.A22

1. the name of the function and the arguments passed to that function

verdict: OK

## E07.Q02.A01

1. Unlike arrays, linked lists can insert and delete without shifting data and change in size easily.

verdict: OK

## E04.Q05.A15

1. All dimensions except for the first one need to be specified when passing an array to a function, the compiler needs to know how many memory addresses to skip to make it back to the 2nd element in the first dimension.
2. The size of the first dimension does not need to be specified.

verdict: OK

## E01.Q01.A11

1. A program that simulates the behavior of portions of the desired software product.

verdict: OK

## E02.Q06.A24

1. A functgion prototype is a declaration of a function , while function definition specifies
2. what a function does

verdict: WRONG, split at mid-sentence wrap

## E11.Q03.A25

1. by giving them a value

verdict: OK

## E08.Q01.A04

1. A list in which only the top (or last item added) can be modified.

verdict: OK

## E01.Q04.A21

1. main

verdict: OK

## E04.Q04.A05

1. a static array will only be initilized once, a non static array will be re-initilized once the program reaches the initilization line again.

verdict: OK
